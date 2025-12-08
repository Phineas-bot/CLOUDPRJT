import shutil
from pathlib import Path
from typing import Optional


class StorageNode:
    def __init__(self, node_id: str, data_dir: str, capacity_bytes: Optional[int] = None):
        self.node_id = node_id
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.capacity_override = capacity_bytes if capacity_bytes and capacity_bytes > 0 else None
        self.used_bytes = self._scan_used_bytes() if self.capacity_override else 0

    def _chunk_path(self, file_id: str, chunk_index: int) -> Path:
        return self.data_dir.joinpath(file_id, f"{chunk_index}.chk")

    def save_chunk(self, file_id: str, chunk_index: int, data: bytes) -> bool:
        target_dir = self.data_dir.joinpath(file_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        path = self._chunk_path(file_id, chunk_index)
        previous_size = path.stat().st_size if path.exists() and self.capacity_override else 0
        path.write_bytes(data)
        if self.capacity_override:
            self.used_bytes = max(0, self.used_bytes - previous_size + len(data))
        return True

    def read_chunk(self, file_id: str, chunk_index: int) -> Optional[bytes]:
        path = self._chunk_path(file_id, chunk_index)
        if not path.exists():
            return None
        return path.read_bytes()

    def delete_chunk(self, file_id: str, chunk_index: int) -> bool:
        path = self._chunk_path(file_id, chunk_index)
        removed = 0
        if path.exists():
            if self.capacity_override:
                removed = path.stat().st_size
            path.unlink()
            # Clean up empty parent dir
            parent = path.parent
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
        if self.capacity_override and removed:
            self.used_bytes = max(0, self.used_bytes - removed)
        return True

    @staticmethod
    def parse_chunk_id(chunk_id: str) -> tuple[str, int]:
        if ":" in chunk_id:
            file_id, idx = chunk_id.rsplit(":", 1)
            try:
                return file_id, int(idx)
            except ValueError:
                return chunk_id, 0
        return chunk_id, 0

    def disk_stats(self) -> tuple[int, int]:
        if self.capacity_override:
            free_bytes = max(0, self.capacity_override - self.used_bytes)
            return self.capacity_override, free_bytes
        # Cross-platform disk stats
        try:
            usage = shutil.disk_usage(self.data_dir)
            return usage.total, usage.free
        except Exception:
            return 0, 0

    def _scan_used_bytes(self) -> int:
        total = 0
        for path in self.data_dir.rglob("*"):
            if path.is_file():
                try:
                    total += path.stat().st_size
                except OSError:
                    continue
        return total
