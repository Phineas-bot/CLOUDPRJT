# Admin Dashboard (Static)

A lightweight static admin dashboard that consumes Gateway endpoints:

- `GET /admin/summary` — aggregate counts (nodes, healthy, pending rebalances)
- `GET /admin/nodes` — node details and health
- `GET /admin/rebalances` — pending rebalance instructions

## Run

Serve the `frontend/admin` directory via any static file server with the Gateway as origin (same host/port). Use the Base URL box to point at the Gateway and set `x-api-key` if `DFS_ADMIN_TOKEN` is enforced. Examples:

```powershell
# from repo root
python -m http.server 8001 --directory frontend/admin
# then browse http://localhost:8001
```

The page auto-refreshes every 5 seconds; use the "Refresh now" button to force an update.
