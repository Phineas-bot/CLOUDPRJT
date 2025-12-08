import json
import os
import sqlite3
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
    load_factor: float = 0.0


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
        self._db_path = os.getenv("DFS_METADATA_DB")
        if self._db_path:
            self._init_db()
            self._load_db()

    # Node management
    def register_node(self, node: NodeState) -> bool:
        with self._lock:
            self._nodes[node.node_id] = node
            self._persist_db_locked()
            return True

    def update_heartbeat(self, node_id: str, free_bytes: int, load_factor: float) -> bool:
        with self._lock:
            node = self._nodes.get(node_id)
            if not node:
                return False
            node.free_bytes = free_bytes
            node.last_seen = time.time()
            node.healthy = True
            node.load_factor = load_factor
            self._persist_db_locked()
            return True

    def mark_unhealthy(self, node_id: str) -> None:
        with self._lock:
            node = self._nodes.get(node_id)
            if node:
                node.healthy = False
                self._persist_db_locked()

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
            self._persist_db_locked()

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
            self._persist_db_locked()

    def overdue_nodes(self) -> List[NodeState]:
        now = time.time()
        with self._lock:
            return [n for n in self._nodes.values() if now - n.last_seen > self._settings.heartbeat_timeout]

    def list_all_nodes(self) -> List[NodeState]:
        with self._lock:
            return list(self._nodes.values())

    # Persistence helpers
    def _init_db(self) -> None:
        conn = sqlite3.connect(self._db_path)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS nodes(
                    node_id TEXT PRIMARY KEY,
                    host TEXT,
                    grpc_port INTEGER,
                    capacity_bytes INTEGER,
                    free_bytes INTEGER,
                    mac TEXT,
                    last_seen REAL,
                    healthy INTEGER,
                    load_factor REAL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS files(
                    file_id TEXT PRIMARY KEY,
                    file_name TEXT,
                    file_size INTEGER,
                    chunk_size INTEGER
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS placements(
                    chunk_id TEXT PRIMARY KEY,
                    file_id TEXT,
                    chunk_index INTEGER,
                    replicas TEXT
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def _persist_db_locked(self) -> None:
        if not self._db_path:
            return
        conn = sqlite3.connect(self._db_path)
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM nodes")
            cur.execute("DELETE FROM files")
            cur.execute("DELETE FROM placements")
            for n in self._nodes.values():
                cur.execute(
                    "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
                    (n.node_id, n.host, n.grpc_port, n.capacity_bytes, n.free_bytes, n.mac, n.last_seen, int(n.healthy), n.load_factor),
                )
            for f in self._files.values():
                cur.execute("INSERT OR REPLACE INTO files VALUES (?,?,?,?)", (f.file_id, f.file_name, f.file_size, f.chunk_size))
                for p in f.placements:
                    cur.execute(
                        "INSERT OR REPLACE INTO placements VALUES (?,?,?,?)",
                        (p.chunk_id, f.file_id, p.chunk_index, json.dumps(p.replicas)),
                    )
            conn.commit()
        finally:
            conn.close()

    def _load_db(self) -> None:
        if not self._db_path or not os.path.exists(self._db_path):
            return
        conn = sqlite3.connect(self._db_path)
        try:
            cur = conn.cursor()
            for row in cur.execute("SELECT node_id, host, grpc_port, capacity_bytes, free_bytes, mac, last_seen, healthy, load_factor FROM nodes"):
                node = NodeState(
                    node_id=row[0],
                    host=row[1],
                    grpc_port=row[2],
                    capacity_bytes=row[3],
                    free_bytes=row[4],
                    mac=row[5],
                    last_seen=row[6],
                    healthy=bool(row[7]),
                    load_factor=row[8] or 0.0,
                )
                self._nodes[node.node_id] = node

            files_lookup: Dict[str, FileRecord] = {}
            for row in cur.execute("SELECT file_id, file_name, file_size, chunk_size FROM files"):
                rec = FileRecord(file_id=row[0], file_name=row[1], file_size=row[2], chunk_size=row[3], placements=[])
                files_lookup[rec.file_id] = rec

            for row in cur.execute("SELECT chunk_id, file_id, chunk_index, replicas FROM placements"):
                replicas = json.loads(row[3]) if row[3] else []
                placement = ChunkPlacement(chunk_id=row[0], chunk_index=row[2], replicas=replicas)
                rec = files_lookup.get(row[1])
                if rec:
                    rec.placements.append(placement)
            self._files = files_lookup
        finally:
            conn.close()
