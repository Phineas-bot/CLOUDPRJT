import math
import secrets
from typing import List, Tuple

from backend.common.config import Settings, load_settings
from backend.master.metadata_store import ChunkPlacement, NodeState


def _pick_nodes(nodes: List[NodeState], replication: int) -> List[NodeState]:
    sorted_nodes = sorted(nodes, key=lambda n: (n.free_bytes, -n.grpc_port), reverse=True)
    return sorted_nodes[:replication]


def plan_upload(file_name: str, file_size: int, settings: Settings | None, healthy_nodes: List[NodeState]) -> Tuple[int, List[ChunkPlacement]]:
    cfg = settings or load_settings()
    chunk_size = cfg.chunk_size
    total_chunks = math.ceil(file_size / chunk_size) if file_size else 1
    placements: List[ChunkPlacement] = []

    for idx in range(total_chunks):
        chunk_id = secrets.token_hex(16)
        target_nodes = _pick_nodes(healthy_nodes, cfg.replication_factor)
        placements.append(
            ChunkPlacement(
                chunk_id=chunk_id,
                chunk_index=idx,
                replicas=[n.node_id for n in target_nodes],
            )
        )

    return chunk_size, placements
