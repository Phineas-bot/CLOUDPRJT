import time
from typing import Optional

from backend.common.config import Settings, load_settings
from backend.master import placement
from backend.master.metadata_store import ChunkPlacement, FileRecord, MetadataStore, NodeState


class MasterService:
    def __init__(self, store: Optional[MetadataStore] = None, settings: Optional[Settings] = None):
        self.settings = settings or load_settings()
        self.store = store or MetadataStore(self.settings)

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

    def get_upload_plan(self, file_name: str, file_size: int, requested_chunk_size: Optional[int] = None) -> tuple[int, list[ChunkPlacement]]:
        if requested_chunk_size and requested_chunk_size > 0:
            self.settings.chunk_size = requested_chunk_size
        healthy = self.store.list_healthy_nodes()
        return placement.plan_upload(file_name, file_size, self.settings, healthy)

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
        self.store.update_chunk_replica(file_id, chunk_id, node_id)

    def get_file_metadata(self, file_id: str) -> Optional[FileRecord]:
        return self.store.get_file(file_id)
