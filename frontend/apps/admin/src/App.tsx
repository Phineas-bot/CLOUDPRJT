import React, { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AdminSummary, NodeDescriptor, RebalanceInstruction, formatBytes, formatDate } from '@shared/index';

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

const App: React.FC = () => {
  const [settings, setSettings] = useState<Settings>(loadSettings);
  const [status, setStatus] = useState('Ready');

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

  const summary = summaryQuery.data;
  const nodes = nodesQuery.data ?? [];
  const rebalances = rebalancesQuery.data ?? [];

  const handleSaveSettings = () => {
    saveSettings(settings);
    setStatus('Settings saved');
    summaryQuery.refetch();
    nodesQuery.refetch();
    rebalancesQuery.refetch();
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
          <header className="sticky top-0 z-10 backdrop-blur bg-slate-900/70 border-b border-slate-800 px-6 py-4 flex flex-wrap items-center gap-4 justify-between">
            <div>
              <p className="text-xs uppercase tracking-wide text-slate-400">Admin</p>
              <h1 className="text-3xl font-bold">Operate the fabric</h1>
              <p className="text-slate-400 text-sm">Clusters, replicas, transfers, observability, governance.</p>
            </div>
            <div className="text-sm text-slate-300">{status}</div>
          </header>

          <main className="p-6 space-y-6">
            <section className="grid gap-4 md:grid-cols-3">
              <MetricCard label="Clusters" value={summary?.node_count ?? 0} sub="active" />
              <MetricCard label="Replication" value={`${summary?.replication_factor ?? 3}x`} sub="target" />
              <MetricCard label="Total chunks" value={summary?.total_chunks?.toLocaleString() ?? '—'} sub="tracked" />
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
                    <NodeCard key={node.node_id} node={node} />
                  ))}
                  {nodes.length === 0 && <p className="text-slate-400">No nodes yet.</p>}
                </div>
              </div>

              <div className="card space-y-3">
                <p className="text-xs uppercase text-slate-400">Gateway</p>
                <label className="text-sm text-slate-300">Base URL</label>
                <input
                  className="input"
                  value={settings.baseUrl}
                  onChange={(e) => setSettings((s) => ({ ...s, baseUrl: e.target.value }))}
                  placeholder="http://localhost:8000"
                />
                <label className="text-sm text-slate-300">x-api-key (optional)</label>
                <input
                  className="input"
                  value={settings.token}
                  onChange={(e) => setSettings((s) => ({ ...s, token: e.target.value }))}
                  placeholder="token"
                />
                <button className="btn w-full" onClick={handleSaveSettings}>Save</button>
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
          </main>
        </div>
      </div>
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

const NodeCard: React.FC<{ node: NodeDescriptor }> = ({ node }) => {
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
      <p className="text-xs text-slate-500 mt-2">Last seen {formatDate(node.last_seen)}</p>
    </div>
  );
};

export default App;
