export type NodeDescriptor = {
  node_id: string;
  host: string;
  grpc_port: number;
  capacity_bytes: number;
  free_bytes: number;
  healthy: boolean;
  last_seen: number;
};

export type RebalanceInstruction = {
  chunk_id: string;
  source_node_id?: string;
  target_node_id: string;
};

export type AdminSummary = {
  node_count: number;
  healthy_nodes: number;
  pending_rebalances: number;
  // Optional extras for richer dashboards
  replication_factor?: number;
  total_chunks?: number;
  total_files?: number;
  active_transfers?: number;
  data_footprint?: string;
  storage_utilization?: number;
  unhealthy_nodes?: number;
};

export type UploadPlan = {
  file_id: string;
  chunk_size: number;
  replication_factor: number;
  placements: Array<{
    chunk_id: string;
    chunk_index: number;
    replicas: Array<{
      node_id: string;
      host: string;
      grpc_port: number;
    }>;
  }>;
};

export type UploadChunkResponse = { ok: boolean; reason?: string };

export type StoredUpload = {
  file_id: string;
  file_name: string;
  file_size: number;
  chunk_size: number;
  uploaded_at: number;
  favorite: boolean;
  trashed: boolean;
  last_accessed: number;
};

export const formatBytes = (bytes: number): string => {
  if (!Number.isFinite(bytes)) return '-';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  let v = bytes;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(1)} ${units[i]}`;
};

export const formatDate = (epochSeconds?: number): string => {
  if (!epochSeconds) return '-';
  return new Date(epochSeconds * 1000).toLocaleString();
};
