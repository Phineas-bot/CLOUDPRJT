import time
from typing import Optional

from backend.common import metrics
from backend.common.config import Settings, load_settings
from backend.master import placement
from backend.master.metadata_store import ChunkPlacement, FileRecord, MetadataStore, NodeState


class MasterService:
    def __init__(self, store: Optional[MetadataStore] = None, settings: Optional[Settings] = None):
        self.settings = settings or load_settings()
        self.store = store or MetadataStore(self.settings)
        # cache of pending rebalances computed by the background scheduler
        self.pending_rebalances: list[tuple[str, str, str]] = []

    # Domain-level helpers (gRPC wiring happens in backend.grpc.master_server)
    def register_node(self, node_id: str, host: str, grpc_port: int, capacity_bytes: int, free_bytes: int, mac: str) -> bool:
        node = NodeState(
            node_id=node_id,
            host=host,
            grpc_port=grpc_port,
            capacity_bytes=capacity_bytes,
            free_bytes=free_bytes,
            mac=mac,
            last_seen=time.time(),
        )
        return self.store.register_node(node)

    def heartbeat(self, node_id: str, free_bytes: int, load_factor: float) -> bool:
        return self.store.update_heartbeat(node_id, free_bytes, load_factor)

    def plan_rebalances(self) -> list[tuple[str, str, str]]:
        healthy = {n.node_id: n for n in self.store.list_healthy_nodes()}
        instructions: list[tuple[str, str, str]] = []
        for file in self.store._files.values():  # pylint: disable=protected-access
            chunk_bytes = file.chunk_size or self.settings.chunk_size
            for placement in file.placements:
                # keep only healthy replicas
                healthy_replicas = [rid for rid in placement.replicas if rid in healthy]
                deficit = self.settings.replication_factor - len(healthy_replicas)
                if deficit <= 0:
                    continue

                # candidate targets: healthy nodes not already holding the chunk with enough free space
                candidate_targets = [
                    n for n in healthy.values() if n.node_id not in placement.replicas and n.free_bytes >= chunk_bytes
                ]
                candidate_targets.sort(key=lambda n: (n.free_bytes, n.capacity_bytes), reverse=True)

                # choose a source replica with the most free space (bias toward healthier hosts)
                source_candidates = sorted(
                    (healthy[rid] for rid in healthy_replicas), key=lambda n: (n.free_bytes, n.capacity_bytes), reverse=True
                )
                # Prefer healthy source with most free space; fallback to the first recorded replica even if now unhealthy
                source_node_id = source_candidates[0].node_id if source_candidates else (placement.replicas[0] if placement.replicas else "")

                for target in candidate_targets[:deficit]:
                    instructions.append((placement.chunk_id, source_node_id, target.node_id))
        return instructions

    def refresh_rebalances(self) -> list[tuple[str, str, str]]:
        """Recompute and store pending rebalances for later delivery."""
        self.pending_rebalances = self.plan_rebalances()
        if self.pending_rebalances:
            metrics.REBALANCE_PLANNED.inc(len(self.pending_rebalances))
        return self.pending_rebalances

    def list_rebalances(self) -> list[tuple[str, str, str]]:
        return list(self.pending_rebalances)

    def take_rebalances_for(self, node_id: str) -> list[tuple[str, str, str]]:
        """Return and remove rebalances targeted at the given node."""
        targeted: list[tuple[str, str, str]] = []
        remaining: list[tuple[str, str, str]] = []
        for chunk_id, source_node, target_node in self.pending_rebalances:
            if target_node == node_id:
                targeted.append((chunk_id, source_node, target_node))
            else:
                remaining.append((chunk_id, source_node, target_node))
        self.pending_rebalances = remaining
        if targeted:
            metrics.REBALANCE_DELIVERED.inc(len(targeted))
        return targeted

    def get_upload_plan(self, file_id: str, file_name: str, file_size: int, requested_chunk_size: Optional[int] = None) -> tuple[int, list[ChunkPlacement]]:
        if requested_chunk_size and requested_chunk_size > 0:
            self.settings.chunk_size = requested_chunk_size
        healthy = self.store.list_healthy_nodes()
        chunk_size, placements = placement.plan_upload(file_id, file_name, file_size, self.settings, healthy)

        # Persist initial file record with planned placements
        record = FileRecord(
            file_id=file_id,
            file_name=file_name,
            file_size=file_size,
            chunk_size=chunk_size,
            placements=placements,
        )
        self.store.put_file(record)
        return chunk_size, placements

    def record_chunk_stored(self, file_id: str, file_name: str, file_size: int, chunk_size: int, chunk_id: str, chunk_index: int, node_id: str) -> None:
        record = self.store.get_file(file_id)
        if not record:
            record = FileRecord(
                file_id=file_id,
                file_name=file_name,
                file_size=file_size,
                chunk_size=chunk_size,
                placements=[],
            )
            self.store.put_file(record)
        self.store.update_chunk_replica(file_id, chunk_id, chunk_index, node_id)

    def get_file_metadata(self, file_id: str) -> Optional[FileRecord]:
        return self.store.get_file(file_id)
