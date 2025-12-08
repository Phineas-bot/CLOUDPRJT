import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from backend.common.config import Settings, load_settings


@dataclass
class NodeState:
    node_id: str
    host: str
    grpc_port: int
    capacity_bytes: int
    free_bytes: int
    mac: str
    last_seen: float
    healthy: bool = True


@dataclass
class ChunkPlacement:
    chunk_id: str
    chunk_index: int
    replicas: List[str] = field(default_factory=list)


@dataclass
class FileRecord:
    file_id: str
    file_name: str
    file_size: int
    chunk_size: int
    placements: List[ChunkPlacement]


class MetadataStore:
    def __init__(self, settings: Optional[Settings] = None):
        self._settings = settings or load_settings()
        self._nodes: Dict[str, NodeState] = {}
        self._files: Dict[str, FileRecord] = {}
        self._lock = threading.RLock()

    # Node management
    def register_node(self, node: NodeState) -> bool:
        with self._lock:
            self._nodes[node.node_id] = node
            return True

    def update_heartbeat(self, node_id: str, free_bytes: int, load_factor: float) -> bool:
        with self._lock:
            node = self._nodes.get(node_id)
            if not node:
                return False
            node.free_bytes = free_bytes
            node.last_seen = time.time()
            node.healthy = True
            return True

    def mark_unhealthy(self, node_id: str) -> None:
        with self._lock:
            node = self._nodes.get(node_id)
            if node:
                node.healthy = False

    def get_node(self, node_id: str) -> Optional[NodeState]:
        with self._lock:
            return self._nodes.get(node_id)

    def list_healthy_nodes(self) -> List[NodeState]:
        now = time.time()
        with self._lock:
            healthy = []
            for node in self._nodes.values():
                if now - node.last_seen <= self._settings.heartbeat_timeout and node.healthy:
                    healthy.append(node)
            return healthy

    # File metadata
    def put_file(self, file_record: FileRecord) -> None:
        with self._lock:
            self._files[file_record.file_id] = file_record

    def get_file(self, file_id: str) -> Optional[FileRecord]:
        with self._lock:
            return self._files.get(file_id)

    def update_chunk_replica(self, file_id: str, chunk_id: str, chunk_index: int, node_id: str) -> None:
        with self._lock:
            rec = self._files.get(file_id)
            if not rec:
                return
            target = None
            for placement in rec.placements:
                if placement.chunk_id == chunk_id:
                    target = placement
                    break
            if target is None:
                target = ChunkPlacement(chunk_id=chunk_id, chunk_index=chunk_index, replicas=[])
                rec.placements.append(target)
            if node_id not in target.replicas:
                target.replicas.append(node_id)

    def overdue_nodes(self) -> List[NodeState]:
        now = time.time()
        with self._lock:
            return [n for n in self._nodes.values() if now - n.last_seen > self._settings.heartbeat_timeout]

    def list_all_nodes(self) -> List[NodeState]:
        with self._lock:
            return list(self._nodes.values())
