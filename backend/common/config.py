import os
from dataclasses import dataclass


def _int_from_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    chunk_size: int = _int_from_env("DFS_CHUNK_SIZE", 4 * 1024 * 1024)
    replication_factor: int = _int_from_env("DFS_REPLICATION", 3)
    heartbeat_interval: int = _int_from_env("DFS_HEARTBEAT_INTERVAL", 5)
    heartbeat_timeout: int = _int_from_env("DFS_HEARTBEAT_TIMEOUT", 15)

    @property
    def as_dict(self) -> dict:
        return self.__dict__


def load_settings() -> Settings:
    return Settings()
