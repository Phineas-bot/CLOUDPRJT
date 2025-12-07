import asyncio
import contextlib
import time

import pytest

from backend.common.config import Settings
from backend.grpc.master_server import _monitor_nodes
from backend.master.metadata_store import MetadataStore
from backend.master.service import MasterService


@pytest.mark.asyncio
async def test_monitor_marks_overdue_nodes_unhealthy():
    settings = Settings(heartbeat_timeout=0.1)
    store = MetadataStore(settings)
    service = MasterService(store=store, settings=settings)

    service.register_node("node1", host="h", grpc_port=1, capacity_bytes=100, free_bytes=80, mac="")
    # Simulate stale heartbeat
    service.store._nodes["node1"].last_seen = time.time() - 1.0

    task = asyncio.create_task(_monitor_nodes(service, interval=0.02))
    await asyncio.sleep(0.06)
    task.cancel()
    with contextlib.suppress(Exception):
        await task

    assert service.store._nodes["node1"].healthy is False


def test_heartbeat_updates_node_metrics():
    settings = Settings(heartbeat_timeout=5)
    store = MetadataStore(settings)
    service = MasterService(store=store, settings=settings)

    service.register_node("node1", host="h", grpc_port=1, capacity_bytes=100, free_bytes=80, mac="")
    before_seen = service.store._nodes["node1"].last_seen
    time.sleep(0.01)

    ok = service.heartbeat("node1", free_bytes=50, load_factor=0.0)

    node = service.store._nodes["node1"]
    assert ok is True
    assert node.free_bytes == 50
    assert node.healthy is True
    assert node.last_seen >= before_seen


def test_list_healthy_nodes_excludes_overdue():
    settings = Settings(heartbeat_timeout=0.01)
    store = MetadataStore(settings)
    service = MasterService(store=store, settings=settings)

    service.register_node("node1", host="h", grpc_port=1, capacity_bytes=100, free_bytes=80, mac="")
    service.register_node("node2", host="h", grpc_port=2, capacity_bytes=100, free_bytes=60, mac="")

    # Make node1 overdue
    service.store._nodes["node1"].last_seen = time.time() - 1.0

    healthy_ids = {n.node_id for n in service.store.list_healthy_nodes()}

    assert "node1" not in healthy_ids
    assert "node2" in healthy_ids
