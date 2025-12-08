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


async def heartbeat_loop(node: StorageNode, stub: pb2_grpc.MasterServiceStub, node_id: str, interval: float) -> None:
    try:
        while True:
            try:
                _, free_bytes = node.disk_stats()
                resp = await stub.Heartbeat(pb2.HeartbeatRequest(node_id=node_id, load_factor=0.0, free_bytes=free_bytes))
                for instr in resp.rebalances:
                    # Only handle instructions targeting this node
                    if instr.target_node_id != node_id:
                        continue
                    # Fetch chunk from source and store locally
                    if not instr.source_node_id:
                        continue
                    await replicate_chunk(node, instr, stub)
            except Exception as exc:  # pragma: no cover
                logging.warning("Heartbeat failed: %s", exc)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:  # graceful shutdown
        return


async def replicate_chunk(node: StorageNode, instr: pb2.RebalanceInstruction, master_stub: pb2_grpc.MasterServiceStub) -> None:
    # Ask master for metadata to locate source host/port
    meta = await master_stub.GetFileMetadata(pb2.FileMetadataRequest(file_id=instr.chunk_id.split(":")[0]))
    placement = next((p for p in meta.placements if p.chunk_id == instr.chunk_id), None)
    if not placement:
        logging.warning("No placement metadata for chunk %s", instr.chunk_id)
        return
    source = next((r for r in placement.replicas if r.node_id == instr.source_node_id), None)
    if not source or not source.host or not source.grpc_port:
        logging.warning("Source node %s missing host/port", instr.source_node_id)
        return

    # Download chunk from source
    channel, stub = await _storage_stub(source.host, source.grpc_port)
    async with channel:
        resp = await stub.DownloadChunk(pb2.DownloadChunkRequest(chunk_id=instr.chunk_id))
    if not resp.ok:
        logging.warning("Failed to pull chunk %s from %s", instr.chunk_id, instr.source_node_id)
        return

    file_id, idx = node.parse_chunk_id(instr.chunk_id)
    node.save_chunk(file_id, idx, resp.data)
    # Inform master we stored it
    await master_stub.ReportChunkStored(
        pb2.ReportChunkStoredRequest(
            file_id=file_id,
            chunk_id=instr.chunk_id,
            chunk_index=idx,
            node_id=instr.target_node_id,
        )
    )


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
    task = asyncio.create_task(heartbeat_loop(node, hb_stub, args.node_id, interval))

    await server.start()
    try:
        await server.wait_for_termination()
    finally:
        task.cancel()
        await hb_channel.close()


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve())
