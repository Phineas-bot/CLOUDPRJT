import React, { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AdminSummary,
  FileRecordSummary,
  NodeDescriptor,
  RebalanceInstruction,
  formatBytes,
  formatDate,
} from '@shared/index';

const SETTINGS_KEY = 'dfs_admin_settings';

type Settings = { baseUrl: string; token: string };

const loadSettings = (): Settings => {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return { baseUrl: 'http://localhost:8000', token: '' };
    const parsed = JSON.parse(raw);
    return { baseUrl: parsed.baseUrl || 'http://localhost:8000', token: parsed.token || '' };
  } catch (err) {
    console.warn('settings load failed', err);
    return { baseUrl: 'http://localhost:8000', token: '' };
  }
};

const saveSettings = (settings: Settings) => localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));

async function fetchJson<T>(baseUrl: string, path: string, token?: string): Promise<T> {
  const resp = await fetch(`${baseUrl}${path}`, {
    headers: token ? { 'x-api-key': token } : undefined,
  });
  if (!resp.ok) throw new Error(`${path} -> ${resp.status}`);
  return resp.json();
}

async function sendJson<T>(
  method: string,
  baseUrl: string,
  path: string,
  token?: string,
  body?: unknown
): Promise<T | undefined> {
  const resp = await fetch(`${baseUrl}${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { 'x-api-key': token } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) throw new Error(`${path} -> ${resp.status}`);
  if (resp.status === 204) return undefined;
  return resp.json() as Promise<T>;
}

const App: React.FC = () => {
  const [settings, setSettings] = useState<Settings>(loadSettings);
  const [status, setStatus] = useState('Ready');
  const [selectedNode, setSelectedNode] = useState<NodeDescriptor | null>(null);
  const [newNode, setNewNode] = useState({ node_id: '', host: '127.0.0.1', grpc_port: 50060 });
  const queryClient = useQueryClient();

  const queryKeyBase = useMemo(() => [settings.baseUrl, settings.token], [settings.baseUrl, settings.token]);

  const summaryQuery = useQuery<AdminSummary>({
    queryKey: [...queryKeyBase, 'summary'],
    queryFn: () => fetchJson(settings.baseUrl, '/admin/summary', settings.token),
    refetchInterval: 5000,
  });

  const nodesQuery = useQuery<NodeDescriptor[]>({
    queryKey: [...queryKeyBase, 'nodes'],
    queryFn: () => fetchJson(settings.baseUrl, '/admin/nodes', settings.token),
    refetchInterval: 5000,
  });

  const rebalancesQuery = useQuery<RebalanceInstruction[]>({
    queryKey: [...queryKeyBase, 'rebalances'],
    queryFn: () => fetchJson(settings.baseUrl, '/admin/rebalances', settings.token),
    refetchInterval: 5000,
  });

  const filesQuery = useQuery<FileRecordSummary[]>({
    queryKey: [...queryKeyBase, 'files'],
    queryFn: () => fetchJson(settings.baseUrl, '/admin/files', settings.token),
    refetchInterval: 5000,
  });

  const summary = summaryQuery.data;
  const nodes = nodesQuery.data ?? [];
  const rebalances = rebalancesQuery.data ?? [];
  const files = filesQuery.data ?? [];

  const handleSaveSettings = () => {
    saveSettings(settings);
    setStatus('Settings saved');
    summaryQuery.refetch();
    nodesQuery.refetch();
    rebalancesQuery.refetch();
    filesQuery.refetch();
  };

  const handleAddNode = async () => {
    if (!newNode.node_id.trim()) {
      setStatus('Provide a node id');
      return;
    }
    setStatus('Provisioning node...');
    try {
      await sendJson('POST', settings.baseUrl, '/admin/nodes/register', settings.token, newNode);
      setStatus(`Node ${newNode.node_id} registered`);
      setNewNode((prev) => ({ ...prev, node_id: '' }));
      await Promise.all([nodesQuery.refetch(), summaryQuery.refetch()]);
    } catch (err: any) {
      setStatus(`Add node failed: ${err.message}`);
    }
  };

  const handleNodeAction = async (nodeId: string, action: 'fail' | 'restore' | 'delete') => {
    const map = {
      fail: { method: 'POST', path: '/admin/nodes/fail', body: { node_id: nodeId }, label: 'Failing' },
      restore: { method: 'POST', path: '/admin/nodes/restore', body: { node_id: nodeId }, label: 'Restoring' },
      delete: { method: 'DELETE', path: `/admin/nodes/${encodeURIComponent(nodeId)}`, body: undefined, label: 'Deleting' },
    } as const;
    const entry = map[action];
    setStatus(`${entry.label} ${nodeId}...`);
    try {
      await sendJson(entry.method, settings.baseUrl, entry.path, settings.token, entry.body);
      setStatus(`${action === 'fail' ? 'Failed' : action === 'restore' ? 'Restored' : 'Deleted'} ${nodeId}`);
      await Promise.all([nodesQuery.refetch(), summaryQuery.refetch()]);
      queryClient.invalidateQueries({ queryKey: [...queryKeyBase, 'files'] });
      if (selectedNode?.node_id === nodeId && action === 'delete') {
        setSelectedNode(null);
      }
    } catch (err: any) {
      setStatus(`Action failed: ${err.message}`);
    }
  };

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_10%_10%,rgba(14,165,233,0.12),transparent_35%),radial-gradient(circle_at_90%_10%,rgba(190,24,93,0.12),transparent_40%),#070d1b] text-slate-100">
      <div className="grid min-h-screen lg:grid-cols-[320px_1fr]">
        {/* Sidebar */}
        <aside className="hidden lg:flex flex-col gap-6 bg-slate-950/70 border-r border-slate-900/70 p-6">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Nexus CloudSim</p>
            <h2 className="text-2xl font-bold">Control Center</h2>
          </div>
          <div className="card space-y-2">
            <p className="text-xs uppercase text-slate-500">SLO burn</p>
            <p className="text-3xl font-bold">0.73x</p>
            <p className="text-xs text-emerald-300">+5% healthier vs last 24h</p>
          </div>
          <div className="grid gap-3">
            <MetricCard label="Capacity" value={`${summary?.storage_utilization ?? 64}%`} sub="Global utilization" />
            <MetricCard label="Transfers" value={`${summary?.active_transfers ?? 3} active`} sub="Pipelines" />
            <MetricCard label="Data" value={summary?.data_footprint ?? '2.56 GB'} sub="Tracked" />
            <MetricCard label="Reliability" value={`${summary?.unhealthy_nodes ?? 1} alerts`} sub="Need attention" />
          </div>
        </aside>

        {/* Main */}
        <div className="flex flex-col min-h-screen">
          <header className="sticky top-0 z-10 backdrop-blur bg-slate-900/70 border-b border-slate-800 px-6 py-4 space-y-3">
            <div className="flex flex-wrap items-center gap-4 justify-between">
              <div>
                <p className="text-xs uppercase tracking-wide text-slate-400">Admin</p>
                <h1 className="text-3xl font-bold">Operate the fabric</h1>
                <p className="text-slate-400 text-sm">Clusters, replicas, transfers, observability, governance.</p>
              </div>
              <div className="text-sm text-slate-300">{status}</div>
            </div>
            <div className="flex flex-wrap gap-3 items-end bg-slate-900/40 border border-slate-800 rounded-lg p-3">
              <div className="flex flex-col text-sm min-w-[220px]">
                <label className="text-slate-400">Gateway URL</label>
                <input
                  className="input"
                  value={settings.baseUrl}
                  onChange={(e) => setSettings((s) => ({ ...s, baseUrl: e.target.value }))}
                  placeholder="http://localhost:8000"
                />
              </div>
              <div className="flex flex-col text-sm min-w-[180px]">
                <label className="text-slate-400">x-api-key</label>
                <input
                  className="input"
                  value={settings.token}
                  onChange={(e) => setSettings((s) => ({ ...s, token: e.target.value }))}
                  placeholder="optional"
                />
              </div>
              <button className="btn" onClick={handleSaveSettings}>Save</button>
            </div>
          </header>

          <main className="p-6 space-y-6">
            <section className="grid gap-4 md:grid-cols-3">
              <MetricCard label="Clusters" value={summary?.node_count ?? 0} sub="active" />
              <MetricCard label="Replication" value={`${summary?.replication_factor ?? 3}x`} sub="target" />
              <MetricCard
                label="Total chunks"
                value={summary?.total_chunks?.toLocaleString() ?? '—'}
                sub="tracked"
              />
            </section>

            <section className="grid gap-4 md:grid-cols-2">
              <MetricCard
                label="Files"
                value={summary?.total_files ?? files.length}
                sub="tracked"
              />
              <MetricCard
                label="Data footprint"
                value={summary?.data_footprint_bytes ? formatBytes(summary.data_footprint_bytes) : '—'}
                sub="stored"
              />
            </section>

            <section className="grid gap-4 xl:grid-cols-[1.7fr_1fr]">
              <div className="card space-y-4">
                <div className="flex items-start justify-between">
                  <div>
                    <p className="text-xs uppercase text-slate-400">Nodes</p>
                    <h2 className="text-xl font-semibold">Health & capacity</h2>
                  </div>
                  <span className="badge">{nodes.length} nodes</span>
                </div>
                <div className="grid md:grid-cols-2 gap-3">
                  {nodes.map((node) => (
                    <NodeCard
                      key={node.node_id}
                      node={node}
                      onInspect={setSelectedNode}
                      onAction={handleNodeAction}
                    />
                  ))}
                  {nodes.length === 0 && <p className="text-slate-400">No nodes yet.</p>}
                </div>
              </div>

              <div className="card space-y-3">
                <p className="text-xs uppercase text-slate-400">Provision node</p>
                <div className="grid gap-2">
                  <label className="text-sm text-slate-300">Node id</label>
                  <input
                    className="input"
                    value={newNode.node_id}
                    onChange={(e) => setNewNode((prev) => ({ ...prev, node_id: e.target.value }))}
                    placeholder="edge-node-3"
                  />
                  <label className="text-sm text-slate-300">Host</label>
                  <input
                    className="input"
                    value={newNode.host}
                    onChange={(e) => setNewNode((prev) => ({ ...prev, host: e.target.value }))}
                    placeholder="127.0.0.1"
                  />
                  <label className="text-sm text-slate-300">gRPC port</label>
                  <input
                    className="input"
                    type="number"
                    value={newNode.grpc_port}
                    onChange={(e) => setNewNode((prev) => ({ ...prev, grpc_port: Number(e.target.value) }))}
                  />
                </div>
                <p className="text-xs text-slate-400">Each node reserves 1&nbsp;GB capacity by default.</p>
                <button className="btn w-full" onClick={handleAddNode}>Add node</button>
              </div>
            </section>

            <section className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
              <div className="card space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs uppercase text-slate-400">Rebalances</p>
                    <h2 className="text-lg font-semibold">Planned actions</h2>
                  </div>
                  <span className="badge">{rebalances.length} pending</span>
                </div>
                <div className="space-y-2">
                  {rebalances.length === 0 && <p className="text-slate-400 text-sm">No rebalances scheduled.</p>}
                  {rebalances.map((r) => (
                    <div key={`${r.chunk_id}-${r.target_node_id}`} className="flex items-start gap-3 border border-slate-800 rounded-lg px-3 py-2">
                      <div className="h-10 w-10 rounded-md bg-slate-800 flex items-center justify-center text-xs text-slate-300">{r.chunk_id.slice(0, 3)}</div>
                      <div className="flex-1 min-w-0">
                        <p className="font-semibold text-sm">Chunk {r.chunk_id}</p>
                        <p className="text-xs text-slate-400">Source {r.source_node_id || 'n/a'} → Target {r.target_node_id}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="card space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs uppercase text-slate-400">Summary</p>
                    <h2 className="text-lg font-semibold">Cluster health</h2>
                  </div>
                  <span className="badge">{summary?.healthy_nodes ?? 0} healthy</span>
                </div>
                <div className="text-sm text-slate-300 space-y-2">
                  <p>Nodes needing attention: {summary?.unhealthy_nodes ?? (summary ? summary.node_count - summary.healthy_nodes : 0)}</p>
                  <p>Total files tracked: {summary?.total_files ?? '—'}</p>
                  <p>Total chunks: {summary?.total_chunks ?? '—'}</p>
                </div>
              </div>
            </section>

            <section className="card space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs uppercase text-slate-400">Files</p>
                  <h2 className="text-lg font-semibold">Stored objects</h2>
                </div>
                <span className="badge">{files.length}</span>
              </div>
              <FilesTable files={files} loading={filesQuery.isLoading} />
            </section>
          </main>
        </div>
      </div>
      {selectedNode && (
        <NodeModal
          node={selectedNode}
          onClose={() => setSelectedNode(null)}
          onAction={handleNodeAction}
        />
      )}
    </div>
  );
};

const MetricCard: React.FC<{ label: string; value: string | number; sub?: string }> = ({ label, value, sub }) => (
  <div className="card">
    <p className="text-xs uppercase text-slate-400">{label}</p>
    <p className="text-3xl font-bold">{value}</p>
    {sub && <p className="text-sm text-slate-400">{sub}</p>}
  </div>
);

type NodeAction = 'fail' | 'restore' | 'delete';

const NodeCard: React.FC<{
  node: NodeDescriptor;
  onInspect: (node: NodeDescriptor) => void;
  onAction: (nodeId: string, action: NodeAction) => void;
}> = ({ node, onInspect, onAction }) => {
  const used = node.capacity_bytes - node.free_bytes;
  const pct = node.capacity_bytes ? Math.round((used / node.capacity_bytes) * 100) : 0;
  return (
    <div className="border border-slate-800 rounded-lg p-3 bg-slate-900/50">
      <div className="flex items-center justify-between">
        <p className="font-semibold">{node.node_id}</p>
        <span className={`badge ${node.healthy ? 'ok' : 'bad'}`}>{node.healthy ? 'Healthy' : 'Unhealthy'}</span>
      </div>
      <p className="text-sm text-slate-400">{node.host}:{node.grpc_port}</p>
      <div className="mt-2 text-sm text-slate-300 flex justify-between">
        <span>{formatBytes(used)} / {formatBytes(node.capacity_bytes)}</span>
        <span>{pct}%</span>
      </div>
      <div className="w-full h-2 rounded-full bg-slate-800 overflow-hidden mt-2">
        <div className="h-full bg-cyan-400" style={{ width: `${pct}%` }}></div>
      </div>
      <div className="text-xs text-slate-500 mt-2 space-y-1">
        <p>Last seen {formatDate(node.last_seen)}</p>
        <p>Load factor {(node.load_factor ?? 0).toFixed(2)}</p>
      </div>
      <div className="flex flex-wrap gap-2 mt-3 text-xs">
        <button className="btn" onClick={() => onInspect(node)}>Inspect</button>
        <button className="btn bg-amber-500/20 text-amber-200" onClick={() => onAction(node.node_id, 'fail')}>
          Fail
        </button>
        <button className="btn bg-emerald-500/20 text-emerald-200" onClick={() => onAction(node.node_id, 'restore')}>
          Restore
        </button>
        <button className="btn bg-rose-600/20 text-rose-200" onClick={() => onAction(node.node_id, 'delete')}>
          Delete
        </button>
      </div>
    </div>
  );
};

const NodeModal: React.FC<{
  node: NodeDescriptor;
  onClose: () => void;
  onAction: (nodeId: string, action: NodeAction) => void;
}> = ({ node, onClose, onAction }) => (
  <div className="fixed inset-0 bg-black/60 flex items-center justify-center p-4">
    <div className="bg-slate-950 border border-slate-800 rounded-xl p-6 w-full max-w-lg space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-xl font-semibold">Inspect {node.node_id}</h3>
        <button className="text-slate-400 hover:text-white" onClick={onClose}>Close</button>
      </div>
      <div className="grid grid-cols-2 gap-3 text-sm">
        <p><span className="text-slate-500">Host</span><br />{node.host}:{node.grpc_port}</p>
        <p><span className="text-slate-500">Status</span><br />{node.healthy ? 'Healthy' : 'Unhealthy'}</p>
        <p><span className="text-slate-500">Capacity</span><br />{formatBytes(node.capacity_bytes)}</p>
        <p><span className="text-slate-500">Free</span><br />{formatBytes(node.free_bytes)}</p>
        <p><span className="text-slate-500">Utilization</span><br />
          {node.capacity_bytes ? `${Math.round(((node.capacity_bytes - node.free_bytes) / node.capacity_bytes) * 100)}%` : '—'}
        </p>
        <p><span className="text-slate-500">Load factor</span><br />{(node.load_factor ?? 0).toFixed(2)}</p>
        <p><span className="text-slate-500">MAC</span><br />{node.mac || '—'}</p>
        <p><span className="text-slate-500">Last seen</span><br />{formatDate(node.last_seen)}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <button className="btn bg-amber-500/20 text-amber-200" onClick={() => onAction(node.node_id, 'fail')}>
          Fail node
        </button>
        <button className="btn bg-emerald-500/20 text-emerald-200" onClick={() => onAction(node.node_id, 'restore')}>
          Restore node
        </button>
        <button className="btn bg-rose-600/20 text-rose-200" onClick={() => onAction(node.node_id, 'delete')}>
          Delete node
        </button>
      </div>
    </div>
  </div>
);

const FilesTable: React.FC<{ files: FileRecordSummary[]; loading: boolean }> = ({ files, loading }) => (
  <div className="overflow-x-auto text-sm">
    {loading && <p className="text-slate-400">Loading files...</p>}
    {!loading && files.length === 0 && <p className="text-slate-400">No files uploaded yet.</p>}
    {!loading && files.length > 0 && (
      <table className="min-w-full">
        <thead>
          <tr className="text-left text-xs uppercase text-slate-500">
            <th className="py-2 pr-3">Name</th>
            <th className="py-2 pr-3">Size</th>
            <th className="py-2 pr-3">Chunks</th>
            <th className="py-2 pr-3">Chunk size</th>
            <th className="py-2 pr-3">File id</th>
          </tr>
        </thead>
        <tbody>
          {files.map((file) => (
            <tr key={file.file_id} className="border-t border-slate-800">
              <td className="py-2 pr-3 font-semibold">{file.file_name || 'Unnamed file'}</td>
              <td className="py-2 pr-3">{formatBytes(file.file_size)}</td>
              <td className="py-2 pr-3">{file.chunk_count}</td>
              <td className="py-2 pr-3">{formatBytes(file.chunk_size)}</td>
              <td className="py-2 pr-3 text-xs break-all text-slate-500">{file.file_id}</td>
            </tr>
          ))}
        </tbody>
      </table>
    )}
  </div>
);

export default App;
