import asyncio
import logging
import os
import time
import uuid
from typing import Literal, Optional

import grpc
import jwt
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from fastapi.responses import StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

try:
    from backend.proto.generated import distributed_storage_pb2 as pb2
    from backend.proto.generated import distributed_storage_pb2_grpc as pb2_grpc
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Run scripts/gen_protos.ps1 to generate gRPC stubs") from exc

from backend.common import metrics
from backend.gateway.auth_store import OtpChallengeStore, UserStore
from backend.gateway.node_manager import NodeManagerError, node_manager
from backend.gateway.notifier import notification_service

ONE_GB = 1024 * 1024 * 1024
AUTH_SECRET = os.getenv("DFS_AUTH_SECRET", "change-me")
TOKEN_TTL = int(os.getenv("DFS_AUTH_TOKEN_TTL", "3600"))

user_store = UserStore()
otp_store = OtpChallengeStore()

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
    route = request.scope.get("route")
    # Use the path template (e.g., /download/{file_id}) to avoid exploding label cardinality
    path = getattr(route, "path_format", None) or getattr(route, "path", None) or request.url.path
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


class NodeRegisterRequest(BaseModel):
    node_id: str
    host: str
    grpc_port: int


class NodeActionBody(BaseModel):
    node_id: str


OtpChannel = Literal["email", "sms", "both"]


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    channel: Optional[OtpChannel] = None


class LoginInitResponse(BaseModel):
    pending_token: str
    expires_in: int
    channels: list[str]


class OtpResendRequest(BaseModel):
    pending_token: str
    channel: Optional[OtpChannel] = None


class OtpVerifyRequest(BaseModel):
    pending_token: str
    code: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


def _serialize_user(record) -> dict:
    return {
        "user_id": record.user_id,
        "email": record.email,
        "phone_number": record.phone_number,
        "otp_channels": record.otp_channels,
        "created_at": record.created_at,
    }


def _create_access_token(user_id: str) -> tuple[str, int]:
    expires_at = int(time.time()) + TOKEN_TTL
    token = jwt.encode({"sub": user_id, "exp": expires_at}, AUTH_SECRET, algorithm="HS256")
    return token, TOKEN_TTL


def _resolve_channels(user, requested: Optional[OtpChannel]) -> list[str]:
    channels = list(user.otp_channels or ["email"])
    if requested and requested != "both":
        if requested not in channels:
            raise HTTPException(status_code=400, detail="requested channel not enabled for user")
        channels = [requested]
    if "sms" in channels and not user.phone_number:
        channels = [ch for ch in channels if ch != "sms"]
    if not channels:
        raise HTTPException(status_code=400, detail="no valid delivery channel configured")
    return channels


async def _dispatch_otp(user, code: str, channels: list[str]) -> None:
    await asyncio.to_thread(
        notification_service.notify,
        email=user.email,
        phone=user.phone_number,
        otp_code=code,
        channels=channels,
    )


def require_user(request: Request) -> str:
    header = request.headers.get("Authorization")
    if not header or not header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = header.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(token, AUTH_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="invalid or expired token") from exc
    return payload.get("sub")


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


async def _node_action(method: str, node_id: str) -> dict:
    channel, stub = await _master_stub()
    async with channel:
        rpc = getattr(stub, method)
        resp = await rpc(pb2.NodeActionRequest(node_id=node_id))
    if not resp.ok:
        raise HTTPException(status_code=400, detail=resp.reason or "node action failed")
    return {"ok": True}


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
            "mac": n.mac,
            "load_factor": n.load_factor,
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
async def fail_node(request: Request, payload: NodeActionBody):
    if not _admin_token_valid(request):
        raise HTTPException(status_code=401, detail="unauthorized")
    if node_manager.is_managed(payload.node_id):
        await node_manager.stop(payload.node_id, remove=False)
    return await _node_action("FailNode", payload.node_id)


@app.post("/admin/nodes/restore")
async def restore_node(request: Request, payload: NodeActionBody):
    if not _admin_token_valid(request):
        raise HTTPException(status_code=401, detail="unauthorized")
    if node_manager.is_managed(payload.node_id):
        try:
            await node_manager.restart(payload.node_id)
        except NodeManagerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await _node_action("RestoreNode", payload.node_id)


@app.delete("/admin/nodes/{node_id}")
async def delete_node(request: Request, node_id: str):
    if not _admin_token_valid(request):
        raise HTTPException(status_code=401, detail="unauthorized")
    if node_manager.is_managed(node_id):
        await node_manager.stop(node_id, remove=True)
    await _node_action("DeleteNode", node_id)
    return Response(status_code=204)


@app.post("/admin/nodes/register")
async def register_node(request: Request, payload: NodeRegisterRequest):
    if not _admin_token_valid(request):
        raise HTTPException(status_code=401, detail="unauthorized")
    try:
        await node_manager.provision(payload.node_id, payload.host, payload.grpc_port, ONE_GB)
    except NodeManagerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@app.get("/admin/summary")
async def admin_summary(request: Request):
    if not _admin_token_valid(request):
        raise HTTPException(status_code=401, detail="unauthorized")
    channel, stub = await _master_stub()
    async with channel:
        nodes_resp = await stub.ListNodes(pb2.ListNodesRequest())
        rebalances_resp = await stub.ListRebalances(pb2.ListRebalancesRequest())
        files_resp = await stub.ListFiles(pb2.ListFilesRequest())

    healthy_nodes = [n for n in nodes_resp.nodes if n.healthy]
    total_files = len(files_resp.files)
    total_chunks = sum(f.chunk_count for f in files_resp.files)
    total_bytes = sum(f.file_size for f in files_resp.files)
    return {
        "node_count": len(nodes_resp.nodes),
        "healthy_nodes": len(healthy_nodes),
        "pending_rebalances": len(rebalances_resp.rebalances),
        "total_files": total_files,
        "total_chunks": total_chunks,
        "data_footprint_bytes": total_bytes,
    }


@app.get("/admin/files")
async def list_files(request: Request):
    if not _admin_token_valid(request):
        raise HTTPException(status_code=401, detail="unauthorized")
    channel, stub = await _master_stub()
    async with channel:
        resp = await stub.ListFiles(pb2.ListFilesRequest())
    return [
        {
            "file_id": f.file_id,
            "file_name": f.file_name,
            "file_size": f.file_size,
            "chunk_size": f.chunk_size,
            "chunk_count": f.chunk_count,
        }
        for f in resp.files
    ]


@app.post("/auth/login", response_model=LoginInitResponse)
async def auth_login(payload: LoginRequest):
    user = user_store.verify_password(payload.email, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="invalid credentials")
    channels = _resolve_channels(user, payload.channel)
    pending_id, code = otp_store.create(user.user_id, channels)
    try:
        await _dispatch_otp(user, code, channels)
    except Exception as exc:  # pragma: no cover - network services
        logging.error("OTP delivery failed for %s: %s", user.email, exc)
        raise HTTPException(status_code=502, detail="failed to deliver otp") from exc
    return LoginInitResponse(pending_token=pending_id, expires_in=otp_store.ttl, channels=channels)


@app.post("/auth/otp/resend", response_model=LoginInitResponse)
async def auth_resend(payload: OtpResendRequest):
    challenge = otp_store.get_challenge(payload.pending_token)
    if not challenge:
        raise HTTPException(status_code=404, detail="challenge expired")
    user = user_store.get(challenge.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="user missing")
    try:
        code, _, stored_channels = otp_store.resend(payload.pending_token)
    except ValueError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    channels = stored_channels
    if payload.channel and payload.channel != "both":
        if payload.channel not in channels:
            raise HTTPException(status_code=400, detail="requested channel not enabled")
        channels = [payload.channel]
    try:
        await _dispatch_otp(user, code, channels)
    except Exception as exc:  # pragma: no cover
        logging.error("OTP resend failed for %s: %s", user.email, exc)
        raise HTTPException(status_code=502, detail="failed to deliver otp") from exc
    return LoginInitResponse(pending_token=payload.pending_token, expires_in=otp_store.ttl, channels=channels)


@app.post("/auth/otp/verify", response_model=TokenResponse)
async def auth_verify(payload: OtpVerifyRequest):
    user_id = otp_store.verify(payload.pending_token, payload.code.strip())
    if not user_id:
        raise HTTPException(status_code=400, detail="invalid or expired code")
    user = user_store.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="user missing")
    token, ttl = _create_access_token(user_id)
    return TokenResponse(access_token=token, expires_in=ttl, user=_serialize_user(user))


@app.get("/auth/me")
async def auth_me(user_id: str = Depends(require_user)):
    user = user_store.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="user missing")
    return _serialize_user(user)


@app.post("/auth/logout")
async def auth_logout():
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
        chunk_data: Optional[bytes] = None
        last_error: Optional[str] = None
        for target in available:
            channel, stub = await _storage_stub(target.host, target.grpc_port)
            async with channel:
                resp = await stub.DownloadChunk(pb2.DownloadChunkRequest(chunk_id=placement.chunk_id))
            if resp.ok:
                chunk_data = resp.data
                break
            last_error = resp.reason or "unknown"
        if chunk_data is None:
            metrics.DOWNLOAD_RESULT.labels(status="chunk_error").inc()
            detail = f"chunk fetch failed after trying {len(available)} replicas: {last_error or 'unknown'}"
            raise HTTPException(status_code=502, detail=detail)
        chunks.append(chunk_data)

    blob = b"".join(chunks)
    metrics.DOWNLOAD_RESULT.labels(status="ok").inc()
    return Response(content=blob, media_type="application/octet-stream")


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
