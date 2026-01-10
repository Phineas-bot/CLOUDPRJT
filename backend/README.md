# Backend Overview

This backend is written in Python and uses gRPC for all inter-service calls. React UIs talk to the Gateway over HTTP. Core pieces:

- `master/`: metadata store, placement policy, heartbeat handling.
- `storage/`: chunk IO on local disk.
- `gateway/`: FastAPI HTTP surface that orchestrates master + storage calls.
- `grpc/`: gRPC server wrappers around domain logic (master + storage).
- `common/`: shared config/utilities.
- `proto/`: protobuf definitions live in repo root `proto/` and should be compiled into `backend/proto/generated/`.

## Getting Started (local dev)
1) Create a virtualenv and install deps: `python -m venv .venv; .\.venv\Scripts\activate; pip install -r backend/requirements.txt`
2) Generate protobuf stubs: `./scripts/gen_protos.ps1`
3) Run the master service: `python -m backend.grpc.master_server`
4) Run a storage node: `NODE_ID=node1 python -m backend.grpc.storage_server --data-dir data/node1 --port 50051`
5) Run gateway API: `python -m backend.gateway.api`

Env hints:
- Set `DFS_AUTH_SECRET` to a strong value (required for JWT + OTP hashing).
- Email OTP options:
	- SendGrid (preferred): `SENDGRID_API_KEY`, `SENDGRID_FROM_EMAIL`.
	- SMTP fallback: `SMTP_HOST`, `SMTP_PORT` (default 587), `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM_EMAIL` (defaults to `SENDGRID_FROM_EMAIL` if set), optional `SMTP_STARTTLS` (default 1 to enable).
- SMS OTP delivery: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`.

## Notes
- Metadata is in-memory for now; snapshotting can be added in `master/metadata_store.py`.
- Storage layout: `data/<node_id>/<file_id>/<chunk_index>.chk`.
- Default chunk size: 4 MiB; replication factor: 3 (configurable via env or config file).
