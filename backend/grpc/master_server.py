import asyncio
import contextlib
import logging
import os
import time
from typing import Optional

import grpc

from backend.common import metrics
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
        # Ensure pending instructions are up to date for interactive calls
        if not self.service.pending_rebalances:
            self.service.refresh_rebalances()
        ok = self.service.heartbeat(
            node_id=request.node_id,
            free_bytes=request.free_bytes,
            load_factor=request.load_factor,
        )
        # deliver only instructions targeted for this node and consume them from the queue
        rebalances = [
            pb2.RebalanceInstruction(chunk_id=cid, source_node_id=src, target_node_id=dst)
            for cid, src, dst in self.service.take_rebalances_for(request.node_id)
        ]
        return pb2.HeartbeatResponse(ok=ok, rebalances=rebalances)

    async def GetUploadPlan(self, request, context):
        chunk_size, placements = self.service.get_upload_plan(
            file_id=request.file_id,
            file_name=request.file_name,
            file_size=request.file_size,
            requested_chunk_size=request.chunk_size,
        )
        healthy_nodes = {n.node_id: n for n in self.service.store.list_healthy_nodes()}
        return pb2.UploadPlanResponse(
            file_id=request.file_id,
            placements=[
                pb2.ChunkPlacement(
                    chunk_id=p.chunk_id,
                    chunk_index=p.chunk_index,
                    replicas=[
                        pb2.NodeDescriptor(
                            node_id=node_id,
                            host=healthy_nodes.get(node_id, None).host if node_id in healthy_nodes else "",
                            grpc_port=healthy_nodes.get(node_id, None).grpc_port if node_id in healthy_nodes else 0,
                            capacity_bytes=healthy_nodes.get(node_id, None).capacity_bytes if node_id in healthy_nodes else 0,
                            free_bytes=healthy_nodes.get(node_id, None).free_bytes if node_id in healthy_nodes else 0,
                            mac=healthy_nodes.get(node_id, None).mac if node_id in healthy_nodes else "",
                            healthy=healthy_nodes.get(node_id, None).healthy if node_id in healthy_nodes else False,
                            last_seen=healthy_nodes.get(node_id, None).last_seen if node_id in healthy_nodes else 0.0,
                            load_factor=healthy_nodes.get(node_id, None).load_factor if node_id in healthy_nodes else 0.0,
                        )
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
        node_lookup = {n.node_id: n for n in self.service.store.list_healthy_nodes()}
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
                        pb2.NodeDescriptor(
                            node_id=r,
                            host=node_lookup.get(r, None).host if r in node_lookup else "",
                            grpc_port=node_lookup.get(r, None).grpc_port if r in node_lookup else 0,
                            capacity_bytes=node_lookup.get(r, None).capacity_bytes if r in node_lookup else 0,
                            free_bytes=node_lookup.get(r, None).free_bytes if r in node_lookup else 0,
                            mac=node_lookup.get(r, None).mac if r in node_lookup else "",
                            healthy=node_lookup.get(r, None).healthy if r in node_lookup else False,
                            last_seen=node_lookup.get(r, None).last_seen if r in node_lookup else 0.0,
                            load_factor=node_lookup.get(r, None).load_factor if r in node_lookup else 0.0,
                        )
                        for r in p.replicas
                    ],
                )
                for p in record.placements
            ],
        )

    async def ListNodes(self, request, context):
        nodes = self.service.store.list_all_nodes()
        return pb2.ListNodesResponse(
            nodes=[
                pb2.NodeDescriptor(
                    node_id=n.node_id,
                    host=n.host,
                    grpc_port=n.grpc_port,
                    capacity_bytes=n.capacity_bytes,
                    free_bytes=n.free_bytes,
                    mac=n.mac,
                    healthy=n.healthy,
                    last_seen=n.last_seen,
                    load_factor=n.load_factor,
                )
                for n in nodes
            ]
        )

    async def ListRebalances(self, request, context):
        return pb2.ListRebalancesResponse(
            rebalances=[
                pb2.RebalanceInstruction(chunk_id=cid, source_node_id=src, target_node_id=dst)
                for cid, src, dst in self.service.list_rebalances()
            ]
        )

    async def FailNode(self, request, context):
        ok = self.service.fail_node(request.node_id)
        reason = "" if ok else "node not found"
        return pb2.NodeActionResponse(ok=ok, reason=reason)

    async def RestoreNode(self, request, context):
        ok = self.service.restore_node(request.node_id)
        reason = "" if ok else "node not found"
        return pb2.NodeActionResponse(ok=ok, reason=reason)

    async def DeleteNode(self, request, context):
        ok = self.service.delete_node(request.node_id)
        reason = "" if ok else "node not found"
        return pb2.NodeActionResponse(ok=ok, reason=reason)

    async def ListFiles(self, request, context):
        files = self.service.list_files()
        return pb2.ListFilesResponse(
            files=[
                pb2.FileSummary(
                    file_id=f.file_id,
                    file_name=f.file_name,
                    file_size=f.file_size,
                    chunk_size=f.chunk_size,
                    chunk_count=len(f.placements),
                )
                for f in files
            ]
        )


def _server_address() -> str:
    host = os.getenv("DFS_MASTER_HOST", "0.0.0.0")
    port = int(os.getenv("DFS_MASTER_PORT", "50050"))
    return f"{host}:{port}"


async def _monitor_nodes(service: MasterService, interval: float) -> None:
    try:
        while True:
            overdue = service.store.overdue_nodes()
            for node in overdue:
                service.store.mark_unhealthy(node.node_id)
                logging.warning("Node %s marked unhealthy (last_seen=%.1fs ago)", node.node_id, time.time() - node.last_seen)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:  # graceful shutdown
        return


async def _rebalance_scheduler(service: MasterService, interval: float) -> None:
    try:
        while True:
            service.refresh_rebalances()
            await asyncio.sleep(interval)
    except asyncio.CancelledError:  # graceful shutdown
        return


async def serve() -> None:
    service = MasterService()
    server = grpc.aio.server()
    pb2_grpc.add_MasterServiceServicer_to_server(MasterGrpc(service), server)
    cert = os.getenv("DFS_TLS_CERT")
    key = os.getenv("DFS_TLS_KEY")
    if cert and key:
        with open(cert, "rb") as f:
            cert_data = f.read()
        with open(key, "rb") as f:
            key_data = f.read()
        server.add_secure_port(_server_address(), grpc.ssl_server_credentials([(key_data, cert_data)]))
        logging.info("Master gRPC listening (TLS) on %s", _server_address())
    else:
        server.add_insecure_port(_server_address())
        logging.info("Master gRPC listening on %s", _server_address())

    # Start housekeeping loop to mark overdue nodes unhealthy
    settings = load_settings()
    monitor_task = asyncio.create_task(_monitor_nodes(service, max(1.0, settings.heartbeat_timeout / 2)))
    rebalance_task = asyncio.create_task(_rebalance_scheduler(service, max(1.0, settings.rebalance_interval)))
    metrics.maybe_start_metrics_server(int(os.getenv("DFS_METRICS_PORT", "0")) or None)

    await server.start()
    try:
        await server.wait_for_termination()
    finally:
        monitor_task.cancel()
        rebalance_task.cancel()
        with contextlib.suppress(Exception):
            await monitor_task
            await rebalance_task


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve())
