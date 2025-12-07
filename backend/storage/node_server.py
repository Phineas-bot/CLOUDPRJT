import shutil
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
        # Cross-platform disk stats
        try:
            usage = shutil.disk_usage(self.data_dir)
            return usage.total, usage.free
        except Exception:
            return 0, 0
