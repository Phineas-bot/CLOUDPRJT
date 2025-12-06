import asyncio
import logging
import os
from typing import Optional

import grpc
from fastapi import FastAPI
from pydantic import BaseModel

try:
    from backend.proto.generated import distributed_storage_pb2 as pb2
    from backend.proto.generated import distributed_storage_pb2_grpc as pb2_grpc
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Run scripts/gen_protos.ps1 to generate gRPC stubs") from exc

app = FastAPI(title="Distributed Storage Gateway", version="0.1.0")


class UploadPlanRequest(BaseModel):
    file_name: str
    file_size: int
    chunk_size: Optional[int] = None


class UploadPlanResponse(BaseModel):
    chunk_size: int
    replication_factor: int
    placements: list[dict]


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
    channel, stub = await _master_stub()
    async with channel:
        reply = await stub.GetUploadPlan(
            pb2.UploadPlanRequest(file_name=req.file_name, file_size=req.file_size, chunk_size=req.chunk_size or 0)
        )
    placements = [
        {
            "chunk_id": p.chunk_id,
            "chunk_index": p.chunk_index,
            "replicas": [r.node_id for r in p.replicas],
        }
        for p in reply.placements
    ]
    return UploadPlanResponse(
        chunk_size=reply.chunk_size,
        replication_factor=reply.replication_factor,
        placements=placements,
    )


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
