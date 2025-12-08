#!/usr/bin/env python3
"""Local launcher for master, gateway, and storage nodes without Docker."""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def start_proc(cmd, env, name):
    print(f"[start] {name}: {' '.join(cmd)}")
    return subprocess.Popen(cmd, env=env)


def parse_args():
    parser = argparse.ArgumentParser(description="Run DFS services locally")
    parser.add_argument("--nodes", type=int, default=2, help="Number of storage nodes")
    parser.add_argument("--base-data-dir", default="data", help="Base directory for storage data")
    parser.add_argument("--master-host", default="127.0.0.1", help="Host for master bind")
    parser.add_argument("--master-port", type=int, default=50050, help="Port for master gRPC")
    parser.add_argument("--gateway-port", type=int, default=8000, help="Port for gateway HTTP")
    parser.add_argument("--storage-base-port", type=int, default=50051, help="Starting port for storage nodes")
    parser.add_argument("--storage-metrics-base", type=int, default=9101, help="Starting metrics port for storage nodes")
    parser.add_argument("--rebalance-interval", type=int, default=5, help="Rebalance interval seconds for master")
    parser.add_argument("--metadata-db", default="", help="Optional SQLite path for master metadata")
    return parser.parse_args()


def main():
    args = parse_args()
    base_env = os.environ.copy()

    master_env = base_env.copy()
    master_env["DFS_HEARTBEAT_INTERVAL"] = master_env.get("DFS_HEARTBEAT_INTERVAL", "5")
    master_env["DFS_HEARTBEAT_TIMEOUT"] = master_env.get("DFS_HEARTBEAT_TIMEOUT", "15")
    master_env["DFS_REBALANCE_INTERVAL"] = str(args.rebalance_interval)
    if args.metadata_db:
        master_env["DFS_METADATA_DB"] = str(args.metadata_db)

    procs = []

    master_cmd = [sys.executable, "-m", "backend.grpc.master_server", "--host", args.master_host, "--port", str(args.master_port)]
    procs.append(start_proc(master_cmd, master_env, "master"))

    gateway_env = base_env.copy()
    gateway_env["DFS_MASTER_HOST"] = args.master_host
    gateway_env["DFS_MASTER_PORT"] = str(args.master_port)
    gateway_cmd = [sys.executable, "-m", "uvicorn", "backend.gateway.api:app", "--host", "0.0.0.0", "--port", str(args.gateway_port)]
    procs.append(start_proc(gateway_cmd, gateway_env, "gateway"))

    base_data_dir = Path(args.base_data_dir)
    for i in range(args.nodes):
        node_id = f"node{i+1}"
        data_dir = base_data_dir / node_id
        ensure_dir(data_dir)
        storage_env = base_env.copy()
        storage_env["DFS_MASTER_HOST"] = args.master_host
        storage_env["DFS_MASTER_PORT"] = str(args.master_port)
        storage_env["NODE_PUBLIC_HOST"] = storage_env.get("NODE_PUBLIC_HOST", "127.0.0.1")
        storage_env["DFS_STORAGE_METRICS_PORT"] = str(args.storage_metrics_base + i)
        port = args.storage_base_port + i
        storage_cmd = [sys.executable, "-m", "backend.grpc.storage_server", "--node-id", node_id, "--data-dir", str(data_dir), "--port", str(port), "--host", "0.0.0.0"]
        procs.append(start_proc(storage_cmd, storage_env, node_id))

    print("All processes started. Press Ctrl+C to stop.")
    try:
        while True:
            for p, name in zip(procs, ["master", "gateway"] + [f"node{i+1}" for i in range(args.nodes)]):
                code = p.poll()
                if code is not None:
                    print(f"[exit] {name} exited with code {code}")
                    raise SystemExit(code)
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping processes...")
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    main()
