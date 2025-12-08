import asyncio
import logging
import os
import time
import uuid
from typing import Optional

import grpc
from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

try:
    from backend.proto.generated import distributed_storage_pb2 as pb2
    from backend.proto.generated import distributed_storage_pb2_grpc as pb2_grpc
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Run scripts/gen_protos.ps1 to generate gRPC stubs") from exc

from backend.common import metrics

app = FastAPI(title="Distributed Storage Gateway", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("DFS_ALLOWED_ORIGINS", "*")],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start
    path = request.url.path
    metrics.REQUEST_COUNT.labels(method=request.method, path=path, status=str(response.status_code)).inc()
    metrics.REQUEST_LATENCY.observe(duration)
    return response


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
    if os.getenv("DFS_MASTER_TLS", "0") == "1":
        ca_path = os.getenv("DFS_MASTER_CA", "")
        creds = grpc.ssl_channel_credentials(root_certificates=open(ca_path, "rb").read() if ca_path else None)
        channel = grpc.aio.secure_channel(_master_target(), creds)
    else:
        channel = grpc.aio.insecure_channel(_master_target())
    stub = pb2_grpc.MasterServiceStub(channel)
    return channel, stub


def _admin_token_valid(request: Request) -> bool:
    expected = os.getenv("DFS_ADMIN_TOKEN")
    if not expected:
        return True
    return request.headers.get("x-api-key") == expected


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/")
async def root():
    return {
        "service": "distributed-storage-gateway",
        "endpoints": ["/health", "/admin/summary", "/admin/nodes", "/admin/rebalances", "/plan", "/upload/chunk", "/download/{file_id}"],
    }


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


@app.get("/metrics")
async def metrics_endpoint():
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


@app.get("/admin/nodes")
async def list_nodes(request: Request):
    if not _admin_token_valid(request):
        raise HTTPException(status_code=401, detail="unauthorized")
    channel, stub = await _master_stub()
    async with channel:
        reply = await stub.ListNodes(pb2.ListNodesRequest())
    return [
        {
            "node_id": n.node_id,
            "host": n.host,
            "grpc_port": n.grpc_port,
            "capacity_bytes": n.capacity_bytes,
            "free_bytes": n.free_bytes,
            "healthy": n.healthy,
            "last_seen": n.last_seen,
        }
        for n in reply.nodes
    ]


@app.get("/admin/rebalances")
async def pending_rebalances(request: Request):
    if not _admin_token_valid(request):
        raise HTTPException(status_code=401, detail="unauthorized")
    channel, stub = await _master_stub()
    async with channel:
        resp = await stub.ListRebalances(pb2.ListRebalancesRequest())
    return [
        {
            "chunk_id": r.chunk_id,
            "source_node_id": r.source_node_id,
            "target_node_id": r.target_node_id,
        }
        for r in resp.rebalances
    ]


@app.post("/admin/nodes/fail")
async def fail_node(request: Request, node_id: str = Form(...)):
    if not _admin_token_valid(request):
        raise HTTPException(status_code=401, detail="unauthorized")
    # Placeholder until master exposes a direct admin RPC
    raise HTTPException(status_code=501, detail="Fail node not yet implemented in master API")


@app.post("/admin/nodes/register")
async def register_node(request: Request, node_id: str = Form(...), host: str = Form(...), grpc_port: int = Form(...)):
    if not _admin_token_valid(request):
        raise HTTPException(status_code=401, detail="unauthorized")
    channel, stub = await _master_stub()
    async with channel:
        resp = await stub.RegisterNode(
            pb2.RegisterNodeRequest(
                node=pb2.NodeDescriptor(
                    node_id=node_id,
                    host=host,
                    grpc_port=grpc_port,
                    capacity_bytes=0,
                    free_bytes=0,
                    mac="",
                )
            )
        )
    if not resp.ok:
        raise HTTPException(status_code=400, detail=resp.reason or "register failed")
    return {"ok": True}


@app.get("/admin/summary")
async def admin_summary(request: Request):
    if not _admin_token_valid(request):
        raise HTTPException(status_code=401, detail="unauthorized")
    channel, stub = await _master_stub()
    async with channel:
        nodes_resp = await stub.ListNodes(pb2.ListNodesRequest())
        rebalances_resp = await stub.ListRebalances(pb2.ListRebalancesRequest())

    healthy_nodes = [n for n in nodes_resp.nodes if n.healthy]
    return {
        "node_count": len(nodes_resp.nodes),
        "healthy_nodes": len(healthy_nodes),
        "pending_rebalances": len(rebalances_resp.rebalances),
    }


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
        metrics.UPLOAD_RESULT.labels(status="error").inc()
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

    metrics.UPLOAD_RESULT.labels(status="ok").inc()
    return ChunkUploadResponse(ok=True, reason=None)


@app.get("/download/{file_id}")
async def download_file(file_id: str):
    channel, stub = await _master_stub()
    async with channel:
        meta = await stub.GetFileMetadata(pb2.FileMetadataRequest(file_id=file_id))
    if not meta.file_id:
        metrics.DOWNLOAD_RESULT.labels(status="not_found").inc()
        raise HTTPException(status_code=404, detail="file not found")

    # Sort placements by index to rebuild original order
    ordered = sorted(meta.placements, key=lambda p: p.chunk_index)
    chunks: list[bytes] = []
    for placement in ordered:
        available = [r for r in placement.replicas if r.host and r.grpc_port]
        if not available:
            metrics.DOWNLOAD_RESULT.labels(status="no_replicas").inc()
            raise HTTPException(status_code=502, detail=f"no replicas for chunk {placement.chunk_id}")
        target = available[0]
        channel, stub = await _storage_stub(target.host, target.grpc_port)
        async with channel:
            resp = await stub.DownloadChunk(pb2.DownloadChunkRequest(chunk_id=placement.chunk_id))
        if not resp.ok:
            metrics.DOWNLOAD_RESULT.labels(status="chunk_error").inc()
            raise HTTPException(status_code=502, detail=f"chunk fetch failed: {resp.reason}")
        chunks.append(resp.data)

    blob = b"".join(chunks)
    metrics.DOWNLOAD_RESULT.labels(status="ok").inc()
    return Response(content=blob, media_type="application/octet-stream")


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
