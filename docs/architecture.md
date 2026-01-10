# Distributed File Storage Architecture

## Goals
- Google-Drive-like UX with upload/download/list/delete.
- Resilient to node loss via replication and re-replication.
- All inter-service traffic uses gRPC + protobuf; UIs talk to gateway over HTTP.

## Components
- **Gateway API (Python + FastAPI)**: HTTP surface for React apps; orchestrates uploads/downloads. Talks to Master over gRPC.
- **Master/Controller (Python + gRPC)**: Source of truth for metadata (files, chunks, node health). Plans placements, tracks heartbeats, schedules re-replication.
- **Storage Node (Python + gRPC)**: Stores chunk files on local disk; exposes upload/download/delete + heartbeat.
- **React User Dashboard**: Drive-like UI for end users (upload, list, download, delete, usage).
- **React Admin Dashboard**: Node list/health, add/remove/fail simulation, replication/usage status. Wire to Gateway endpoints `/admin/nodes`, `/admin/rebalances`, and `/admin/summary` for health and rebalance counts.

## Data Model (Master)
- **File**: `file_id`, `name`, `size`, `chunk_size`, `total_chunks`.
- **Chunk**: `chunk_id`, `file_id`, `index`, `replica_nodes[]`.
- **Node**: `node_id`, `host`, `grpc_port`, `capacity_bytes`, `free_bytes`, `health`, `last_seen`, `mac`.

## Flows
- **Upload**: Gateway requests `UploadPlan` from Master → splits file into chunks → streams chunks to Storage Nodes → each node stores chunk and returns ack → Gateway notifies Master (`ReportChunkStored`) → Master persists metadata.
- **Download**: Gateway asks Master for file metadata → streams chunk downloads from storage nodes in parallel → reassembles and streams to client.
- **Heartbeat**: Storage nodes send heartbeats to Master; Master marks health and may issue re-replication instructions.
- **Re-replication**: When health changes, Master schedules missing replicas and instructs Gateway/Storage to copy chunks.

## gRPC Contracts (high level)
- **MasterService**: RegisterNode, Heartbeat, GetUploadPlan, ReportChunkStored, GetFileMetadata.
- **StorageService**: UploadChunk, DownloadChunk, DeleteChunk, HealthCheck.
- **(Optional) GatewayService**: For node-initiated calls if needed later.

## Storage Layout (per storage node)
- Root: `data/<node_id>/`
- Chunk path: `data/<node_id>/<file_id>/<chunk_index>.chk`

## Configuration
- Chunk size default: 4 MiB (configurable).
- Replication factor default: 3 (configurable).
- Heartbeat interval default: 5s; timeout default: 15s.

## Repo Layout (planned)
- `proto/` – protobuf definitions.
- `backend/`
  - `common/` – shared config/utilities.
  - `master/` – metadata + placement.
  - `storage/` – chunk IO + node process.
  - `gateway/` – FastAPI HTTP surface.
  - `grpc/` – gRPC server wrappers around domain logic.
  - `requirements.txt` – Python deps.
- `frontend/`
  - `user/` – React user dashboard (future).
  - `admin/` – React admin dashboard (future).
- `scripts/` – helper scripts (proto generation, local cluster helpers).

## MVP Scope
- In-memory metadata with optional snapshot to disk.
- Local chunk storage with mkdirs per node.
- Basic placement policy: choose least-loaded healthy nodes.
- Happy-path upload/download through Gateway using gRPC to Master/Storage.
- CLI runner scripts to start master, gateway, and sample storage nodes.

## Next Steps
- Implement re-replication worker and background health sweeps.
- Add auth + TLS for gRPC.
- Add persistence for metadata (SQLite) and chunk checksuming.
- Build React dashboards hitting Gateway.
