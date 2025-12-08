import asyncio
import os
from contextlib import AsyncExitStack

import grpc
import httpx
from httpx import ASGITransport
import pytest

from backend.common.config import Settings
from backend.gateway.api import app
from backend.grpc.master_server import MasterGrpc
from backend.grpc.storage_server import StorageGrpc
from backend.master.metadata_store import MetadataStore, FileRecord, ChunkPlacement
from backend.master.service import MasterService
from backend.storage.node_server import StorageNode

try:
    from backend.proto.generated import distributed_storage_pb2 as pb2
    from backend.proto.generated import distributed_storage_pb2_grpc as pb2_grpc
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Run scripts/gen_protos.ps1 to generate gRPC stubs before tests") from exc


@pytest.mark.asyncio
async def test_upload_and_download_roundtrip(tmp_path, monkeypatch):
    # Configure small chunk size and replication=1 for simplicity
    monkeypatch.setenv("DFS_CHUNK_SIZE", "1024")
    monkeypatch.setenv("DFS_REPLICATION", "1")

    settings = Settings()
    store = MetadataStore(settings)
    master_service = MasterService(store=store, settings=settings)

    master_server = grpc.aio.server()
    pb2_grpc.add_MasterServiceServicer_to_server(MasterGrpc(master_service), master_server)
    master_port = master_server.add_insecure_port("localhost:0")
    await master_server.start()

    # Point gateway to this master
    monkeypatch.setenv("DFS_MASTER_HOST", "localhost")
    monkeypatch.setenv("DFS_MASTER_PORT", str(master_port))

    # Start storage server
    storage_node = StorageNode("node1", data_dir=tmp_path / "node1")
    storage_server = grpc.aio.server()
    pb2_grpc.add_StorageServiceServicer_to_server(StorageGrpc(storage_node), storage_server)
    storage_port = storage_server.add_insecure_port("localhost:0")
    await storage_server.start()

    # Register node with master directly
    master_service.register_node(
        node_id="node1",
        host="localhost",
        grpc_port=storage_port,
        capacity_bytes=10_000,
        free_bytes=9_000,
        mac="",
    )

    file_bytes = b"hello e2e world"

    async with AsyncExitStack() as stack:
        transport = ASGITransport(app=app)
        client = httpx.AsyncClient(transport=transport, base_url="http://test")
        await stack.enter_async_context(client)

        # Plan upload
        plan_resp = await client.post(
            "/plan",
            json={"file_name": "test.bin", "file_size": len(file_bytes), "chunk_size": settings.chunk_size},
        )
        plan_resp.raise_for_status()
        payload = plan_resp.json()

        placement = payload["placements"][0]
        replica = placement["replicas"][0]

        # Upload chunk via gateway
        upload_resp = await client.post(
            "/upload/chunk",
            data={
                "file_id": payload["file_id"],
                "chunk_id": placement["chunk_id"],
                "chunk_index": placement["chunk_index"],
                "node_id": replica["node_id"],
                "node_host": replica["host"],
                "node_port": replica["grpc_port"],
            },
            files={"chunk": ("chunk.bin", file_bytes, "application/octet-stream")},
        )
        upload_resp.raise_for_status()
        assert upload_resp.json()["ok"] is True

        # Download full file
        download_resp = await client.get(f"/download/{payload['file_id']}")
        download_resp.raise_for_status()
        assert download_resp.content == file_bytes


@pytest.mark.asyncio
async def test_download_missing_replicas_returns_error(tmp_path, monkeypatch):
    monkeypatch.setenv("DFS_CHUNK_SIZE", "1024")
    monkeypatch.setenv("DFS_REPLICATION", "1")

    settings = Settings()
    store = MetadataStore(settings)
    master_service = MasterService(store=store, settings=settings)

    master_server = grpc.aio.server()
    pb2_grpc.add_MasterServiceServicer_to_server(MasterGrpc(master_service), master_server)
    master_port = master_server.add_insecure_port("localhost:0")
    await master_server.start()

    monkeypatch.setenv("DFS_MASTER_HOST", "localhost")
    monkeypatch.setenv("DFS_MASTER_PORT", str(master_port))

    # Record file with placement but no replicas
    store.put_file(
        FileRecord(
            file_id="file-missing",
            file_name="missing.bin",
            file_size=1,
            chunk_size=1024,
            placements=[ChunkPlacement(chunk_id="file-missing:0", chunk_index=0, replicas=[])],
        )
    )

    async with AsyncExitStack() as stack:
        transport = ASGITransport(app=app)
        client = httpx.AsyncClient(transport=transport, base_url="http://test")
        await stack.enter_async_context(client)

        resp = await client.get("/download/file-missing")
        assert resp.status_code == 502

    await master_server.stop(0)
    await master_server.stop(0)
