import os
from pathlib import Path
from typing import Optional


class StorageNode:
    def __init__(self, node_id: str, data_dir: str):
        self.node_id = node_id
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _chunk_path(self, file_id: str, chunk_index: int) -> Path:
        return self.data_dir.joinpath(file_id, f"{chunk_index}.chk")

    def save_chunk(self, file_id: str, chunk_index: int, data: bytes) -> bool:
        target_dir = self.data_dir.joinpath(file_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        path = self._chunk_path(file_id, chunk_index)
        path.write_bytes(data)
        return True

    def read_chunk(self, file_id: str, chunk_index: int) -> Optional[bytes]:
        path = self._chunk_path(file_id, chunk_index)
        if not path.exists():
            return None
        return path.read_bytes()

    def delete_chunk(self, file_id: str, chunk_index: int) -> bool:
        path = self._chunk_path(file_id, chunk_index)
        if path.exists():
            path.unlink()
            # Clean up empty parent dir
            parent = path.parent
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
        return True

    def disk_stats(self) -> tuple[int, int]:
        usage = os.statvfs(str(self.data_dir))
        capacity = usage.f_blocks * usage.f_frsize
        free = usage.f_bavail * usage.f_frsize
        return capacity, free
