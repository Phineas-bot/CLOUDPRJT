# DFS Frontend (Vite + React + TypeScript + Tailwind)

Two apps share a workspace:
- `apps/user`: upload/download client
- `apps/admin`: cluster health dashboard

## Prereqs
- Node 18+
- npm (workspaces enabled)

## Install
```powershell
cd frontend
npm install
```

## Run dev
```powershell
npm run dev:user   # starts user app on 5173
npm run dev:admin  # starts admin app on 5174
```

Auth options
- Password + OTP (existing flow)

## Build
```powershell
npm run build --workspaces
```

## Notes
- Tailwind and shared types live in `packages/shared`.
- Configure Gateway base URL and optional `x-api-key` inside each app UI.
- User app performs `/plan` then `/upload/chunk` for each replica, and downloads via `/download/{file_id}`.
- Admin app polls `/admin/summary`, `/admin/nodes`, `/admin/rebalances` every 5s (manual refresh available).
