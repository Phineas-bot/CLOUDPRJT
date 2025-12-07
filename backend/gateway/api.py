import asyncio
import logging
import os
import uuid
from typing import Optional

import grpc
from fastapi import FastAPI, File, Form, UploadFile
from pydantic import BaseModel

try:
    from backend.proto.generated import distributed_storage_pb2 as pb2
    from backend.proto.generated import distributed_storage_pb2_grpc as pb2_grpc
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Run scripts/gen_protos.ps1 to generate gRPC stubs") from exc

app = FastAPI(title="Distributed Storage Gateway", version="0.1.0")


class UploadPlanRequest(BaseModel):
    file_id: Optional[str] = None
    file_name: str
    file_size: int
    chunk_size: Optional[int] = None


class UploadPlanResponse(BaseModel):
    file_id: str
    chunk_size: int
    replication_factor: int
    placements: list[dict]


class ChunkUploadResponse(BaseModel):
    ok: bool
    reason: Optional[str] = None


def _master_target() -> str:
    host = os.getenv("DFS_MASTER_HOST", "localhost")
    port = int(os.getenv("DFS_MASTER_PORT", "50050"))
    return f"{host}:{port}"


async def _master_stub():
    channel = grpc.aio.insecure_channel(_master_target())
    stub = pb2_grpc.MasterServiceStub(channel)
    return channel, stub


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/plan", response_model=UploadPlanResponse)
async def get_plan(req: UploadPlanRequest):
    file_id = req.file_id or uuid.uuid4().hex
    channel, stub = await _master_stub()
    async with channel:
        reply = await stub.GetUploadPlan(
            pb2.UploadPlanRequest(file_id=file_id, file_name=req.file_name, file_size=req.file_size, chunk_size=req.chunk_size or 0)
        )
    placements = [
        {
            "chunk_id": p.chunk_id,
            "chunk_index": p.chunk_index,
            "replicas": [
                {
                    "node_id": r.node_id,
                    "host": r.host,
                    "grpc_port": r.grpc_port,
                }
                for r in p.replicas
            ],
        }
        for p in reply.placements
    ]
    return UploadPlanResponse(
        file_id=reply.file_id,
        chunk_size=reply.chunk_size,
        replication_factor=reply.replication_factor,
        placements=placements,
    )


async def _storage_stub(host: str, port: int):
    target = f"{host}:{port}"
    channel = grpc.aio.insecure_channel(target)
    stub = pb2_grpc.StorageServiceStub(channel)
    return channel, stub


@app.post("/upload/chunk", response_model=ChunkUploadResponse)
async def upload_chunk(
    file_id: str = Form(...),
    chunk_id: str = Form(...),
    chunk_index: int = Form(...),
    node_id: str = Form(...),
    node_host: str = Form(...),
    node_port: int = Form(...),
    chunk: UploadFile = File(...),
):
    data = await chunk.read()

    # Write chunk to storage node
    channel, stub = await _storage_stub(node_host, node_port)
    async with channel:
        upload_resp = await stub.UploadChunk(
            pb2.UploadChunkRequest(file_id=file_id, chunk_id=chunk_id, chunk_index=chunk_index, data=data)
        )
    if not upload_resp.ok:
        return ChunkUploadResponse(ok=False, reason=upload_resp.reason)

    # Notify master that replica stored
    master_channel, master_stub = await _master_stub()
    async with master_channel:
        await master_stub.ReportChunkStored(
            pb2.ReportChunkStoredRequest(
                file_id=file_id,
                chunk_id=chunk_id,
                chunk_index=chunk_index,
                node_id=node_id,
            )
        )

    return ChunkUploadResponse(ok=True, reason=None)


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
