import asyncio
import contextlib

import pytest

from backend.grpc.storage_server import heartbeat_loop

try:
    from backend.proto.generated import distributed_storage_pb2 as pb2
except ImportError:  # pragma: no cover - stubs not generated in some environments
    pb2 = None


class FakeNode:
    def __init__(self, free_values):
        self._free_values = list(free_values)
        self._last = free_values[0]

    def disk_stats(self):
        if self._free_values:
            self._last = self._free_values.pop(0)
        return 0, self._last


class FakeStub:
    def __init__(self):
        self.calls = []

    async def Heartbeat(self, req):
        self.calls.append(req)


@pytest.mark.asyncio
async def test_heartbeat_loop_sends_heartbeats():
    if pb2 is None:
        pytest.skip("protobuf stubs not generated")

    node = FakeNode([100, 90, 80])
    stub = FakeStub()

    task = asyncio.create_task(heartbeat_loop(node, stub, "node1", 0.01))
    await asyncio.sleep(0.035)
    task.cancel()
    with contextlib.suppress(Exception):
        await task

    assert len(stub.calls) >= 2
    assert all(call.node_id == "node1" for call in stub.calls)
    free_values = {call.free_bytes for call in stub.calls}
    assert free_values <= {100, 90, 80}
