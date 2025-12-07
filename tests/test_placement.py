import time

from backend.common.config import Settings
from backend.master import placement
from backend.master.metadata_store import NodeState


def make_node(node_id: str, free_bytes: int, last_seen: float | None = None, healthy: bool = True) -> NodeState:
    now = time.time()
    return NodeState(
        node_id=node_id,
        host="h",
        grpc_port=1,
        capacity_bytes=100,
        free_bytes=free_bytes,
        mac="",
        last_seen=last_seen or now,
        healthy=healthy,
    )


def test_plan_upload_respects_replication_and_capacity_order():
    settings = Settings(chunk_size=4, replication_factor=2)
    nodes = [make_node("n1", 50), make_node("n2", 80), make_node("n3", 20)]

    chunk_size, placements = placement.plan_upload(
        file_id="file1", file_name="f", file_size=10, settings=settings, healthy_nodes=nodes
    )

    assert chunk_size == 4
    # total_chunks = ceil(10/4) = 3
    assert len(placements) == 3
    for p in placements:
        assert len(p.replicas) == 2
        # Top two by free_bytes are n2 (80) and n1 (50)
        assert set(p.replicas) == {"n1", "n2"}
