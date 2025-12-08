import asyncio
import os
import shutil
import sys
from asyncio.subprocess import Process
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

MANAGED_DATA_DIR_ENV = "DFS_MANAGED_DATA_DIR"


class NodeManagerError(RuntimeError):
    """Base error for managed node lifecycle issues."""


class NodeAlreadyRunning(NodeManagerError):
    pass


class NodeNotFound(NodeManagerError):
    pass


@dataclass
class ManagedNode:
    node_id: str
    host: str
    grpc_port: int
    capacity_bytes: int
    data_dir: Path
    process: Optional[Process] = None
    status: str = "stopped"


class NodeManager:
    def __init__(self) -> None:
        self._nodes: Dict[str, ManagedNode] = {}
        self._lock = asyncio.Lock()

    def is_managed(self, node_id: str) -> bool:
        return node_id in self._nodes

    def get(self, node_id: str) -> Optional[ManagedNode]:
        return self._nodes.get(node_id)

    async def provision(self, node_id: str, host: str, grpc_port: int, capacity_bytes: int) -> ManagedNode:
        async with self._lock:
            existing = self._nodes.get(node_id)
            if existing and existing.process and existing.process.returncode is None:
                raise NodeAlreadyRunning(f"Node {node_id} is already running")
            data_dir = self._data_dir_for(node_id)
            data_dir.mkdir(parents=True, exist_ok=True)
            process = await self._spawn(node_id, host, grpc_port, capacity_bytes, data_dir)
            managed = ManagedNode(
                node_id=node_id,
                host=host,
                grpc_port=grpc_port,
                capacity_bytes=capacity_bytes,
                data_dir=data_dir,
                process=process,
                status="running",
            )
            self._nodes[node_id] = managed
            return managed

    async def restart(self, node_id: str) -> ManagedNode:
        async with self._lock:
            managed = self._nodes.get(node_id)
            if not managed:
                raise NodeNotFound(f"Node {node_id} is not managed")
            if managed.process and managed.process.returncode is None:
                return managed
            process = await self._spawn(managed.node_id, managed.host, managed.grpc_port, managed.capacity_bytes, managed.data_dir)
            managed.process = process
            managed.status = "running"
            return managed

    async def stop(self, node_id: str, *, remove: bool = False) -> bool:
        async with self._lock:
            managed = self._nodes.get(node_id)
            if not managed:
                return False
            await self._terminate(managed)
            managed.process = None
            managed.status = "stopped"
            if remove:
                if managed.data_dir.exists():
                    shutil.rmtree(managed.data_dir, ignore_errors=True)
                del self._nodes[node_id]
            return True

    async def _terminate(self, managed: ManagedNode) -> None:
        proc = managed.process
        if not proc:
            return
        if proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()

    async def _spawn(self, node_id: str, host: str, grpc_port: int, capacity_bytes: int, data_dir: Path) -> Process:
        env = os.environ.copy()
        env.setdefault("DFS_MASTER_HOST", os.getenv("DFS_MASTER_HOST", "localhost"))
        env.setdefault("DFS_MASTER_PORT", os.getenv("DFS_MASTER_PORT", "50050"))
        env["NODE_PUBLIC_HOST"] = host
        env["NODE_CAPACITY_BYTES"] = str(capacity_bytes)
        cmd = [
            sys.executable,
            "-m",
            "backend.grpc.storage_server",
            "--node-id",
            node_id,
            "--data-dir",
            str(data_dir),
            "--port",
            str(grpc_port),
            "--host",
            "0.0.0.0",
            "--capacity-bytes",
            str(capacity_bytes),
        ]
        process = await asyncio.create_subprocess_exec(*cmd, env=env)
        await asyncio.sleep(0.5)
        if process.returncode is not None:
            raise NodeManagerError(f"Managed node {node_id} exited immediately with code {process.returncode}")
        return process

    def _data_dir_for(self, node_id: str) -> Path:
        base = Path(os.getenv(MANAGED_DATA_DIR_ENV, "data/managed"))
        return base / node_id


node_manager = NodeManager()
