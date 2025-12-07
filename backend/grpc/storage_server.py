import argparse
import asyncio
import logging
import os
from typing import Optional

import grpc

from backend.storage.node_server import StorageNode

try:
    from backend.proto.generated import distributed_storage_pb2 as pb2
    from backend.proto.generated import distributed_storage_pb2_grpc as pb2_grpc
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Run scripts/gen_protos.ps1 to generate gRPC stubs") from exc


class StorageGrpc(pb2_grpc.StorageServiceServicer):
    def __init__(self, node: StorageNode):
        self.node = node

    async def UploadChunk(self, request, context):
        ok = self.node.save_chunk(request.file_id, request.chunk_index, request.data)
        return pb2.UploadChunkResponse(ok=ok, reason="")

    async def DownloadChunk(self, request, context):
        file_id, idx = self.node.parse_chunk_id(request.chunk_id)
        data = self.node.read_chunk(file_id, idx)
        if data is None:
            return pb2.DownloadChunkResponse(ok=False, data=b"", reason="not found")
        return pb2.DownloadChunkResponse(ok=True, data=data, reason="")

    async def DeleteChunk(self, request, context):
        file_id, idx = self.node.parse_chunk_id(request.chunk_id)
        ok = self.node.delete_chunk(file_id, idx)
        return pb2.DeleteChunkResponse(ok=ok, reason="")

    async def HealthCheck(self, request, context):
        return pb2.HealthCheckResponse(ok=True, status="ok")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Storage node gRPC server")
    parser.add_argument("--node-id", default=os.getenv("NODE_ID", "node1"))
    parser.add_argument("--data-dir", default=os.getenv("DATA_DIR", "data/node1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "50051")))
    parser.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    return parser.parse_args()


def _address(host: str, port: int) -> str:
    return f"{host}:{port}"


async def serve(args: Optional[argparse.Namespace] = None) -> None:
    args = args or _parse_args()
    node = StorageNode(args.node_id, args.data_dir)
    server = grpc.aio.server()
    pb2_grpc.add_StorageServiceServicer_to_server(StorageGrpc(node), server)
    server.add_insecure_port(_address(args.host, args.port))
    logging.info("Storage node %s listening on %s", args.node_id, _address(args.host, args.port))

    # Register with master if configured
    master_host = os.getenv("DFS_MASTER_HOST", "localhost")
    master_port = int(os.getenv("DFS_MASTER_PORT", "50050"))
    register_channel = grpc.aio.insecure_channel(f"{master_host}:{master_port}")
    register_stub = pb2_grpc.MasterServiceStub(register_channel)
    capacity, free = node.disk_stats()
    public_host = os.getenv("NODE_PUBLIC_HOST", args.host)
    try:
        async with register_channel:
            await register_stub.RegisterNode(
                pb2.RegisterNodeRequest(
                    node=pb2.NodeDescriptor(
                        node_id=args.node_id,
                        host=public_host,
                        grpc_port=args.port,
                        capacity_bytes=capacity,
                        free_bytes=free,
                        mac="",
                    )
                )
            )
            logging.info("Registered node %s with master %s:%s", args.node_id, master_host, master_port)
    except Exception as exc:  # pragma: no cover - network/env issues
        logging.warning("Failed to register node with master: %s", exc)

    # Heartbeat loop
    hb_channel = grpc.aio.insecure_channel(f"{master_host}:{master_port}")
    hb_stub = pb2_grpc.MasterServiceStub(hb_channel)
    interval = int(os.getenv("DFS_HEARTBEAT_INTERVAL", "5"))

    async def heartbeat_task():
        while True:
            try:
                _, free_bytes = node.disk_stats()
                await hb_stub.Heartbeat(
                    pb2.HeartbeatRequest(node_id=args.node_id, load_factor=0.0, free_bytes=free_bytes)
                )
            except Exception as exc:  # pragma: no cover
                logging.warning("Heartbeat failed: %s", exc)
            await asyncio.sleep(interval)

    task = asyncio.create_task(heartbeat_task())

    await server.start()
    try:
        await server.wait_for_termination()
    finally:
        task.cancel()
        await hb_channel.close()


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve())
