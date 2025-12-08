from __future__ import annotations

from typing import Optional, Set

from prometheus_client import Counter, Histogram, start_http_server

# Counters for rebalance lifecycle
REBALANCE_PLANNED = Counter("rebalance_planned_total", "Rebalance instructions planned")
REBALANCE_DELIVERED = Counter("rebalance_delivered_total", "Rebalance instructions delivered to nodes")
REBALANCE_SUCCEEDED = Counter("rebalance_succeeded_total", "Rebalance instructions that completed successfully")
REBALANCE_FAILED = Counter("rebalance_failed_total", "Rebalance instructions that failed")

# Gateway request metrics
REQUEST_COUNT = Counter("gateway_requests_total", "Gateway requests", labelnames=["method", "path", "status"])
REQUEST_LATENCY = Histogram(
    "gateway_request_duration_seconds",
    "Gateway request duration",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
UPLOAD_RESULT = Counter("gateway_upload_total", "Upload outcomes", labelnames=["status"])
DOWNLOAD_RESULT = Counter("gateway_download_total", "Download outcomes", labelnames=["status"])

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
