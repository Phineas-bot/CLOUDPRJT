# User Dashboard (Static)

A lightweight client for uploads and downloads via the Gateway.

## Features
- Request upload plan, chunk the file, and upload replicas to storage via Gateway.
- Store recent uploads locally (file id, name, size, chunk size) for quick downloads.
- Download by file id using the Gateway `/download/{file_id}` endpoint.
- Configurable Gateway base URL and optional `x-api-key` header if the Gateway enforces `DFS_ADMIN_TOKEN`.

## Run
Serve the `frontend/user` directory via any static server that can reach the Gateway origin. Examples:

```powershell
# from repo root
python -m http.server 8002 --directory frontend/user
# browse http://localhost:8002
```

Defaults assume Gateway on `http://localhost:8000`. Use the Base URL box to point elsewhere.
