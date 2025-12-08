from __future__ import annotations

from typing import Optional, Set

from prometheus_client import Counter, start_http_server

# Counters for rebalance lifecycle
REBALANCE_PLANNED = Counter("rebalance_planned_total", "Rebalance instructions planned")
REBALANCE_DELIVERED = Counter("rebalance_delivered_total", "Rebalance instructions delivered to nodes")
REBALANCE_SUCCEEDED = Counter("rebalance_succeeded_total", "Rebalance instructions that completed successfully")
REBALANCE_FAILED = Counter("rebalance_failed_total", "Rebalance instructions that failed")

_started_ports: Set[int] = set()


def maybe_start_metrics_server(port: Optional[int]) -> None:
    """Start a Prometheus metrics HTTP server if a valid port is provided.

    Safe to call multiple times; will only start once per port.
    """
    if not port:
        return
    if port in _started_ports:
        return
    start_http_server(port)
    _started_ports.add(port)
