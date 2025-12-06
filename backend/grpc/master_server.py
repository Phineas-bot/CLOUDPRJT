import asyncio
import logging
import os
from typing import Optional

import grpc

from backend.common.config import load_settings
from backend.master.service import MasterService

try:
    from backend.proto.generated import distributed_storage_pb2 as pb2
    from backend.proto.generated import distributed_storage_pb2_grpc as pb2_grpc
except ImportError as exc:  # pragma: no cover - guidance for missing stubs
    raise RuntimeError("Run scripts/gen_protos.ps1 to generate gRPC stubs") from exc


class MasterGrpc(pb2_grpc.MasterServiceServicer):
    def __init__(self, service: Optional[MasterService] = None):
        self.service = service or MasterService()

    async def RegisterNode(self, request, context):
        ok = self.service.register_node(
            node_id=request.node.node_id,
            host=request.node.host,
            grpc_port=request.node.grpc_port,
            capacity_bytes=request.node.capacity_bytes,
            free_bytes=request.node.free_bytes,
            mac=request.node.mac,
        )
        return pb2.RegisterNodeResponse(ok=ok, reason="")

    async def Heartbeat(self, request, context):
        ok = self.service.heartbeat(
            node_id=request.node_id,
            free_bytes=request.free_bytes,
            load_factor=request.load_factor,
        )
        return pb2.HeartbeatResponse(ok=ok, rebalances=[])

    async def GetUploadPlan(self, request, context):
        chunk_size, placements = self.service.get_upload_plan(
            file_name=request.file_name,
            file_size=request.file_size,
            requested_chunk_size=request.chunk_size,
        )
        return pb2.UploadPlanResponse(
            placements=[
                pb2.ChunkPlacement(
                    chunk_id=p.chunk_id,
                    chunk_index=p.chunk_index,
                    replicas=[
                        pb2.NodeDescriptor(node_id=node_id, host="", grpc_port=0, capacity_bytes=0, free_bytes=0, mac="")
                        for node_id in p.replicas
                    ],
                )
                for p in placements
            ],
            chunk_size=chunk_size,
            replication_factor=load_settings().replication_factor,
        )

    async def ReportChunkStored(self, request, context):
        self.service.record_chunk_stored(
            file_id=request.file_id,
            file_name="",  # Gateway should fill this in future
            file_size=0,
            chunk_size=request.chunk_size if hasattr(request, "chunk_size") else load_settings().chunk_size,
            chunk_id=request.chunk_id,
            chunk_index=request.chunk_index,
            node_id=request.node_id,
        )
        return pb2.ReportChunkStoredResponse(ok=True)

    async def GetFileMetadata(self, request, context):
        record = self.service.get_file_metadata(request.file_id)
        if not record:
            return pb2.FileMetadataResponse()
        return pb2.FileMetadataResponse(
            file_id=record.file_id,
            file_name=record.file_name,
            file_size=record.file_size,
            chunk_size=record.chunk_size,
            placements=[
                pb2.ChunkPlacement(
                    chunk_id=p.chunk_id,
                    chunk_index=p.chunk_index,
                    replicas=[
                        pb2.NodeDescriptor(node_id=r, host="", grpc_port=0, capacity_bytes=0, free_bytes=0, mac="")
                        for r in p.replicas
                    ],
                )
                for p in record.placements
            ],
        )


def _server_address() -> str:
    host = os.getenv("DFS_MASTER_HOST", "0.0.0.0")
    port = int(os.getenv("DFS_MASTER_PORT", "50050"))
    return f"{host}:{port}"


async def serve() -> None:
    server = grpc.aio.server()
    pb2_grpc.add_MasterServiceServicer_to_server(MasterGrpc(), server)
    server.add_insecure_port(_server_address())
    logging.info("Master gRPC listening on %s", _server_address())
    await server.start()
    await server.wait_for_termination()


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve())
