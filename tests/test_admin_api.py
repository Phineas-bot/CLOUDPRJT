import asyncio
from contextlib import AsyncExitStack

import grpc
import httpx
import pytest
from httpx import ASGITransport

from backend.gateway.api import app
from backend.grpc.master_server import MasterGrpc
from backend.master.metadata_store import MetadataStore, NodeState
from backend.master.service import MasterService

try:
    from backend.proto.generated import distributed_storage_pb2 as pb2
    from backend.proto.generated import distributed_storage_pb2_grpc as pb2_grpc
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Run scripts/gen_protos.ps1 to generate gRPC stubs before tests") from exc


@pytest.mark.asyncio
async def test_admin_nodes_endpoint(tmp_path, monkeypatch):
    settings = None
    store = MetadataStore(settings)
    svc = MasterService(store=store, settings=settings)

    # Start master server
    master_server = grpc.aio.server()
    pb2_grpc.add_MasterServiceServicer_to_server(MasterGrpc(svc), master_server)
    master_port = master_server.add_insecure_port("localhost:0")
    await master_server.start()

    monkeypatch.setenv("DFS_MASTER_HOST", "localhost")
    monkeypatch.setenv("DFS_MASTER_PORT", str(master_port))

    # Register nodes
    svc.register_node("n1", host="localhost", grpc_port=1234, capacity_bytes=100, free_bytes=90, mac="")
    svc.register_node("n2", host="localhost", grpc_port=1235, capacity_bytes=100, free_bytes=10, mac="")

    async with AsyncExitStack() as stack:
        client = httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        await stack.enter_async_context(client)

        resp = await client.get("/admin/nodes")
        resp.raise_for_status()
        nodes = resp.json()
        ids = {n["node_id"] for n in nodes}
        assert {"n1", "n2"} <= ids

    await master_server.stop(0)
