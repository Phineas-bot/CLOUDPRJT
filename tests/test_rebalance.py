import time

import pytest

from backend.common.config import Settings
from backend.grpc.master_server import MasterGrpc
from backend.master.metadata_store import ChunkPlacement, FileRecord, MetadataStore, NodeState
from backend.master.service import MasterService


def make_node(node_id: str, healthy: bool = True, last_seen: float | None = None) -> NodeState:
    return NodeState(
        node_id=node_id,
        host="h",
        grpc_port=1234,
        capacity_bytes=100,
        free_bytes=80,
        mac="",
        last_seen=last_seen or time.time(),
        healthy=healthy,
    )


def test_plan_rebalances_suggests_new_target_when_replica_unhealthy():
    settings = Settings(replication_factor=2)
    store = MetadataStore(settings)
    n1 = make_node("n1", healthy=True)
    n2 = make_node("n2", healthy=False, last_seen=time.time() - 100)
    store.register_node(n1)
    store.register_node(n2)

    store.put_file(
        FileRecord(
            file_id="f1",
            file_name="f1",
            file_size=10,
            chunk_size=4,
            placements=[ChunkPlacement(chunk_id="f1:0", chunk_index=0, replicas=["n2"])],
        )
    )

    svc = MasterService(store=store, settings=settings)
    rebalances = svc.plan_rebalances()

    assert rebalances == [("f1:0", "n2", "n1")]


@pytest.mark.asyncio
async def test_heartbeat_returns_rebalance_instructions():
    settings = Settings(replication_factor=1)
    store = MetadataStore(settings)
    n1 = make_node("n1", healthy=True)
    store.register_node(n1)
    svc = MasterService(store=store, settings=settings)
    store.put_file(
        FileRecord(
            file_id="f2",
            file_name="f2",
            file_size=4,
            chunk_size=4,
            placements=[ChunkPlacement(chunk_id="f2:0", chunk_index=0, replicas=[])],
        )
    )

    grpc = MasterGrpc(svc)
    resp = await grpc.Heartbeat(type("Req", (), {"node_id": "n1", "free_bytes": 50, "load_factor": 0.0}), None)

    assert resp.rebalances
    instr = resp.rebalances[0]
    assert instr.chunk_id == "f2:0"
    assert instr.target_node_id == "n1"
