# GitHub Copilot Instructions for This Repo

## Project Overview
- This repo is a **distributed file storage system** (Google-Drive-like) built from scratch.
- Core stack:
  - **Python + gRPC** for backend services (master/controller + storage nodes + gateway API).
  - **React** for the **User Dashboard** and **Admin Dashboard**.
  - **Local disk** is used for chunk storage on each storage node (no external storage service).
- All inter-service communication should use **gRPC with protobufs**, not REST.

## High-Level Architecture
- **Master/Controller Node**
  - Owns **metadata**: file → chunks → nodes, node health, node capacity, basic node identity (IP, MAC, etc.).
  - Handles: node heartbeats, upload routing, replication planning, detecting node failure, and re-replication.
  - Exposes gRPC services for the gateway and (optionally) storage nodes to query/update metadata.
- **Storage Nodes**
  - Store file **chunks** on the local filesystem (e.g. under a node-specific `data/` directory).
  - Expose gRPC methods like uploadChunk, downloadChunk, deleteChunk, heartbeat.
  - Must be able to dynamically **join/leave** the cluster; master treats nodes as ephemeral.
- **Gateway / API Layer**
  - React frontends never talk directly to master or storage nodes; they talk to a Python API/gateway over HTTP or gRPC.
  - Gateway coordinates with the master to:
    - Split files into chunks.
    - Obtain target nodes for each chunk.
    - Orchestrate uploads/downloads via storage nodes.
- **React UIs**
  - **User Dashboard**: upload/download, list files, delete, show usage; behaves like a simplified Google Drive.
  - **Admin Dashboard**: view node list and health, add/remove/simulate-fail nodes, show metrics (storage usage, number of chunks, replication state).

## Core Domain Rules & Data Flow
- **Chunking**
  - Files are split into **fixed-size chunks** (e.g. 4 MB); chunk size should be centrally configurable.
  - Upload flow: UI → Gateway → Master (plan) → Storage Nodes (store chunks) → Master (confirm metadata).
  - Download flow: UI → Gateway → Master (locate chunks) → Storage Nodes (stream chunks) → Gateway → UI.
- **Replication**
  - Each chunk has a **replication factor** (3 copies) that must be honored when assigning nodes.
  - Master is responsible for scheduling extra replicas and **re-replicating** after node failures.
- **Node Health & Scaling**
  - Storage nodes send periodic **heartbeats** to master.
  - Master marks nodes as healthy/unhealthy and updates placement decisions accordingly.
  - Admin UI actions to add/remove/fail nodes should eventually map to changes in master’s metadata + node lifecycle.

## Patterns & Conventions to Follow
- **gRPC / Protobuf**
  - Define clear service boundaries: master service, storage node service, gateway service.
  - Favor explicit messages for file upload/download, chunk placement, heartbeats, node membership, and metadata queries.
- **Storage Layout**
  - Use deterministic on-disk layout per node, such as `data/<node_id>/<chunk_id>` or `data/<node_id>/<file_id>/<chunk_index>`.
  - Never couple front-end file naming directly to on-disk paths; always go through metadata.
- **Metadata**
  - Keep the master as the **single source of truth** for:
    - File descriptors (name, size, type, number of chunks).
    - Chunk descriptors (chunk index, owning file, list of node IDs).
    - Node descriptors (ID, capacity, IP/MAC, health status).
  - Backing store can be in-memory with periodic snapshots, or a simple DB like SQLite.

## Workflows for Agents
- **When adding backend features**
  - Start from the domain concept: does this belong to **master**, **storage node**, or **gateway**?
  - Extend protobuf definitions first, then regenerate stubs, then implement service methods.
  - Ensure new operations are reflected end-to-end (master ↔ storage node ↔ gateway ↔ UI if needed).
- **When extending the React UIs**
  - User Dashboard: focus on file-level operations (upload, list, download, delete, quota/usage visualization).
  - Admin Dashboard: focus on node-level operations (add/remove/fail, heartbeat/health views, replication/usage status).
  - All calls should go through the gateway/backend APIs, not directly to nodes.
- **Testing and simulation**
  - Prefer small local clusters: 1 master + 2–4 storage nodes started as separate processes (or via `docker-compose` when available).
  - Design helpers/scripts to spin up multiple nodes with distinct data directories and ports.

## Things to Avoid
- Do **not** introduce REST between services; keep internal comms gRPC-based.
- Do **not** bypass the master when deciding where chunks go; storage nodes should not self-assign responsibility.
- Avoid hardcoding local paths or node IDs; use configuration where possible.

## TODO / Unknowns for This Repo
- Concrete file layout, module names, and existing scripts are not yet present.
- When these get added (e.g. `backend/`, `frontend/`, `proto/`), update this file with:
  - Actual directory names.
  - Exact commands for running master/node/gateway and building React apps.
  - Any project-specific linting/testing workflows.
