
---

# 🚀 Distributed File Storage System (Google-Drive-Like)

A scalable, fault-tolerant distributed file storage system built **from scratch** using:

* **Python** for backend services
* **gRPC** for all internal communication
* **React** for both the User UI and Admin UI
* **Local-disk chunk storage** (no external storage services)

This system supports dynamic node scaling, replication, node failure handling, and a Google-Drive-style user experience.

---

## 📌 Project Overview

This project implements a distributed file system similar to Google Drive.
Users can upload, download, browse, and delete files.
Administrators can manage and monitor the storage cluster.

The system is composed of:

* **Storage Nodes** (store file chunks on local disk)
* **Master/Controller Node** (metadata, coordination, replication, node monitoring)
* **React User Dashboard** (Drive-like interface)
* **React Admin Panel** (monitor and control nodes)

All communication is done through **gRPC**.

---

## ⚙️ Core Features

### ✔ Distributed File Storage

* Files are **split into chunks** (e.g., 4MB each)
* Chunks are distributed across multiple storage nodes
* Uses **local filesystem** on each node (`/data/nodeX/...`)
* Replication factor configurable (e.g., 3 copies per chunk)

### ✔ Master Node (Controller)

Responsible for:

* Metadata tracking (files → chunks → nodes)
* Node health monitoring (heartbeats)
* Assigning nodes for uploads
* Detecting failed nodes
* Re-replicating chunks when failures occur
* Load balancing across nodes

### ✔ Storage Nodes

Each node:

* Stores chunks locally
* Exposes gRPC API: upload, download, delete, heartbeat
* Joins or leaves the cluster dynamically
* Can be “failed” manually via admin UI

### ✔ Node Scaling

* Nodes can be added or removed anytime
* System redistributes and replicates chunks automatically

### ✔ Fault Tolerance

* If a node fails, system detects it and re-replicates missing chunks
* Metadata ensures no broken files

---

## 🖥 User Interface (React)

### **User Dashboard**

A Google-Drive-style interface with:

* File upload (supports large files via chunking)
* File download
* File listing, preview, and deletion
* Usage information

### **Admin Dashboard**

Used to control the cluster:

* View all nodes and their health
* Add nodes
* Remove nodes
* Simulate node failures
* Real-time monitoring of:

  * node status
  * storage usage
  * number of chunks
  * replication health

---

## 🔌 Communication Architecture

All system communication uses **gRPC**:

* User UI → Gateway API
* Gateway → Master Node
* Master → Storage Nodes
* Storage Node ↔ Storage Node (optional for optimization)

Protocol buffers define:

* File upload/download
* Chunk distribution
* Node heartbeat
* Node join/leave
* Metadata operations

---

## 🗄 Storage Model

### **File Handling**

1. File is split into fixed-size chunks
2. Master node chooses storage nodes
3. Each node stores chunk in a local directory
4. Metadata service records file structure

### **Metadata Storage**

Metadata includes:

* File name, size, type
* Number of chunks
* Nodes holding each chunk
* Node health + capacity, node IP + MAC

Can be implemented with:

* In-memory tables + periodic snapshots
  or
* SQLite (simple and stable)

---


## 🔧 Technical Requirements

### Backend

* Python
* gRPC + Protocol Buffers
* Threading or asyncio
* Local file storage
* Health monitoring + heartbeats
* Chunking & replication logic
* Node scaling and membership

### Frontend

* React
* Admin panel + user panel
* File upload with chunk splitting
* Real-time node monitoring dashboards

---

## 🎯 Deliverables

* Fully functional distributed storage backend
* Master node + storage nodes implementation
* gRPC protobuf definitions
* React User Dashboard
* React Admin Dashboard
* Scripts or docker-compose to simulate multiple nodes
* Documentation + setup instructions

---

## 🔐 Authentication & Local Login

The gateway keeps user credentials in `data/user_store.json`. In a fresh checkout this file does not exist, so you need to seed at least one account before the React dashboards can log in.

Set `DFS_USER_STORE` if you want to store the file elsewhere, otherwise the default path under `data/` is used. Then run:

```
cd backend
python -m backend.scripts.create_user admin@example.com --password "SuperSecret123" --channels email
```

Use `--force` to update the password of an existing email, and `--phone`/`--channels email,sms` to enable SMS OTP delivery.

Alternatively, you can seed a user automatically at startup by exporting `DFS_DEFAULT_USER_EMAIL` and `DFS_DEFAULT_USER_PASSWORD` before launching `backend/gateway/api.py`.

---




---

