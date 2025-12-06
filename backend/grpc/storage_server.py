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
        # chunk_id maps to file_id; simple scheme chunk_id = file_id:chunk_index could be added later
        data = self.node.read_chunk(request.chunk_id, 0)
        if data is None:
            return pb2.DownloadChunkResponse(ok=False, data=b"", reason="not found")
        return pb2.DownloadChunkResponse(ok=True, data=data, reason="")

    async def DeleteChunk(self, request, context):
        ok = self.node.delete_chunk(request.chunk_id, 0)
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
    await server.start()
    await server.wait_for_termination()


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve())
