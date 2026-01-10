type Tab = 'drive' | 'recent' | 'favorites' | 'trash' | 'search';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  UploadPlan,
  UploadChunkResponse,
  StoredUpload,
  formatBytes,
  AuthSession,
  PendingChallenge,
  OtpChannel,
  login as requestLogin,
  signup as requestSignup,
  resendOtp,
  verifyOtp,
  saveSession,
  loadSession,
  fetchMe,
} from '@shared/index';

const UPLOADS_KEY = 'dfs_user_uploads';
const SESSION_KEY = 'dfs_user_session';
const CHUNK_LOG_KEY = 'dfs_chunk_activity';
const MB = 1024 * 1024;
const STORAGE_LIMIT_BYTES = 2 * 1024 * 1024 * 1024; // 2 GB per user
// Default to gateway's local port from docker-compose/run_local
const BASE_URL = import.meta.env.VITE_GATEWAY_URL ?? 'http://localhost:8000';

type ChunkLogEntry = { message: string; ts: number };



const NAV_ITEMS: { key: Tab; label: string }[] = [
  { key: 'drive', label: 'My Drive' },
  { key: 'recent', label: 'Recent' },
  { key: 'favorites', label: 'Favorites' },
  { key: 'trash', label: 'Trash' },
  { key: 'search', label: 'Search' },
];

const determineChunkSize = (fileSize: number): number => {
  if (!fileSize) return 4 * MB;
  if (fileSize <= 8 * MB) return 1 * MB;
  if (fileSize <= 64 * MB) return 2 * MB;
  if (fileSize <= 256 * MB) return 4 * MB;
  if (fileSize <= 1024 * MB) return 8 * MB;
  return 16 * MB;
};

const normalizeUpload = (raw: StoredUpload): StoredUpload => ({
  file_id: raw.file_id,
  file_name: raw.file_name,
  file_size: raw.file_size,
  chunk_size: raw.chunk_size,
  uploaded_at: raw.uploaded_at ?? Date.now(),
  favorite: raw.favorite ?? false,
  trashed: raw.trashed ?? false,
  last_accessed: raw.last_accessed ?? raw.uploaded_at ?? Date.now(),
});

const loadUploads = (key: string): StoredUpload[] => {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw).map(normalizeUpload) : [];
  } catch (err) {
    console.warn('uploads load failed', err);
    return [];
  }
};
const persistUploads = (key: string, uploads: StoredUpload[]) => localStorage.setItem(key, JSON.stringify(uploads));

const readChunkLog = (): ChunkLogEntry[] => {
  try {
    const raw = localStorage.getItem(CHUNK_LOG_KEY);
    return raw ? (JSON.parse(raw) as ChunkLogEntry[]) : [];
  } catch (err) {
    console.warn('chunk log load failed', err);
    return [];
  }
};

const pushChunkLog = (message: string) => {
  const next = [{ message, ts: Date.now() }, ...readChunkLog()].slice(0, 50);
  localStorage.setItem(CHUNK_LOG_KEY, JSON.stringify(next));
};

const App: React.FC = () => {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [session, setSession] = useState<AuthSession | null>(() => loadSession(SESSION_KEY));
  const uploadsKey = useMemo(
    () => (session?.user?.user_id ? `${UPLOADS_KEY}_${session.user.user_id}` : `${UPLOADS_KEY}_anon`),
    [session?.user?.user_id]
  );
  const [uploads, setUploads] = useState<StoredUpload[]>(() => loadUploads(uploadsKey));
  const [activeTab, setActiveTab] = useState<Tab>('drive');
  const [downloadQuery, setDownloadQuery] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [status, setStatus] = useState('Idle');
  const [isUploading, setIsUploading] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [downloadProgress, setDownloadProgress] = useState(0);
  const [pendingChunkSize, setPendingChunkSize] = useState<number | null>(null);
  const [pendingChallenge, setPendingChallenge] = useState<PendingChallenge | null>(null);
  const [loginForm, setLoginForm] = useState({ email: '', password: '', channel: 'email' as OtpChannel });
  const [signupForm, setSignupForm] = useState({ email: '', password: '', phone_number: '', channel: 'email' as OtpChannel });
  const [authMode, setAuthMode] = useState<'login' | 'signup'>('login');
  const [showPassword, setShowPassword] = useState(false);
  const [otpCode, setOtpCode] = useState('');
  const [authError, setAuthError] = useState<string | null>(null);
  const [authStatus, setAuthStatus] = useState('Sign in to continue');
  const [authBusy, setAuthBusy] = useState(false);

  useEffect(() => {
    setUploads(loadUploads(uploadsKey));
  }, [uploadsKey]);

  useEffect(() => {
    if (!session) {
      setAuthStatus('Sign in to continue');
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const user = await fetchMe(BASE_URL, session.token);
        if (cancelled) return;
        const refreshed = { ...session, user } as AuthSession;
        setSession(refreshed);
        saveSession(SESSION_KEY, refreshed);
        setAuthStatus(`Signed in as ${user.email}`);
      } catch (err) {
        if (cancelled) return;
        saveSession(SESSION_KEY, null);
        setSession(null);
        resetAuthFlow();
        setAuthError('Session expired. Please sign in again.');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [session?.token]);

  const nonTrashedUploads = useMemo(() => uploads.filter((u) => !u.trashed), [uploads]);
  const favoritesCount = useMemo(() => uploads.filter((u) => u.favorite && !u.trashed).length, [uploads]);
  const storageUsedBytes = useMemo(
    () => nonTrashedUploads.reduce((sum, u) => sum + u.file_size, 0),
    [nonTrashedUploads]
  );
  const storageRemainingBytes = useMemo(
    () => Math.max(0, STORAGE_LIMIT_BYTES - storageUsedBytes),
    [storageUsedBytes]
  );

  const filteredUploads = useMemo(() => {
    const base = uploads;
    switch (activeTab) {
      case 'favorites':
        return base.filter((u) => u.favorite && !u.trashed);
      case 'trash':
        return base.filter((u) => u.trashed);
      case 'recent':
        return base.filter((u) => !u.trashed).sort((a, b) => b.uploaded_at - a.uploaded_at);
      case 'search': {
        const q = searchQuery.trim().toLowerCase();
        if (!q) return base.filter((u) => !u.trashed);
        return base.filter(
          (u) =>
            !u.trashed &&
            (u.file_name.toLowerCase().includes(q) || u.file_id.toLowerCase().includes(q))
        );
      }
      default:
        return base.filter((u) => !u.trashed);
    }
  }, [uploads, activeTab, searchQuery]);

  const updateUploads = useCallback(
    (updater: (prev: StoredUpload[]) => StoredUpload[]) => {
      setUploads((prev) => {
        const next = updater(prev).map(normalizeUpload);
        persistUploads(uploadsKey, next);
        return next;
      });
    },
    [uploadsKey]
  );

  const upsertUpload = useCallback(
    (record: StoredUpload) => {
      updateUploads((prev) => {
        const idx = prev.findIndex((u) => u.file_id === record.file_id);
        if (idx >= 0) {
          const copy = [...prev];
          copy[idx] = normalizeUpload({ ...copy[idx], ...record });
          return copy;
        }
        return [normalizeUpload(record), ...prev];
      });
    },
    [updateUploads]
  );

  const toggleFavorite = (fileId: string) => {
    updateUploads((prev) =>
      prev.map((u) => (u.file_id === fileId ? { ...u, favorite: !u.favorite, last_accessed: Date.now() } : u))
    );
  };

  const moveToTrash = (fileId: string, value: boolean) => {
    updateUploads((prev) => prev.map((u) => (u.file_id === fileId ? { ...u, trashed: value } : u)));
  };

  const deleteForever = (fileId: string) => {
    updateUploads((prev) => prev.filter((u) => u.file_id !== fileId));
  };

  const handleFilePick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    setPendingChunkSize(file ? determineChunkSize(file.size) : null);
  };

  const resetAuthFlow = () => {
    setPendingChallenge(null);
    setOtpCode('');
    setAuthError(null);
    setAuthStatus('Sign in to continue');
    setAuthMode('login');
  };

  const handleLogout = () => {
    saveSession(SESSION_KEY, null);
    setSession(null);
    resetAuthFlow();
    setAuthStatus('Sign in to continue');
  };

  const handleLoginSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setAuthBusy(true);
    setAuthError(null);
    try {
      const resp = await requestLogin(BASE_URL, loginForm);
      setPendingChallenge(resp);
      setAuthStatus(`OTP sent via ${resp.channels.join(', ')}`);
      setOtpCode('');
    } catch (err: any) {
      setAuthError(err.message || 'Login failed');
    } finally {
      setAuthBusy(false);
    }
  };

  const handleOtpVerify = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!pendingChallenge) return;
    setAuthBusy(true);
    setAuthError(null);
    try {
      const freshSession = await verifyOtp(BASE_URL, {
        pending_token: pendingChallenge.pending_token,
        code: otpCode.trim(),
      });
      setSession(freshSession);
      saveSession(SESSION_KEY, freshSession);
      resetAuthFlow();
      setAuthStatus(`Signed in as ${freshSession.user.email}`);
    } catch (err: any) {
      setAuthError(err.message || 'Invalid code');
    } finally {
      setAuthBusy(false);
    }
  };

  const handleSignupSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setAuthBusy(true);
    setAuthError(null);
    try {
      const payload = {
        email: signupForm.email,
        password: signupForm.password,
        phone_number: signupForm.phone_number || undefined,
        channel: signupForm.channel,
      };
      const resp = await requestSignup(BASE_URL, payload);
      setPendingChallenge(resp);
      setAuthStatus(`OTP sent via ${resp.channels.join(', ')}`);
      setOtpCode('');
      setAuthMode('login');
      setLoginForm({ email: signupForm.email, password: signupForm.password, channel: signupForm.channel });
    } catch (err: any) {
      setAuthError(err.message || 'Signup failed');
    } finally {
      setAuthBusy(false);
    }
  };

  const handleResendOtp = async () => {
    if (!pendingChallenge) return;
    setAuthBusy(true);
    setAuthError(null);
    try {
      const resp = await resendOtp(BASE_URL, { pending_token: pendingChallenge.pending_token });
      setPendingChallenge(resp);
      setAuthStatus(`New code sent (${resp.channels.join(', ')})`);
    } catch (err: any) {
      setAuthError(err.message || 'Resend failed');
    } finally {
      setAuthBusy(false);
    }
  };

  const handleUpload = useCallback(async () => {
    if (!session) {
      setStatus('Sign in to upload');
      return;
    }
    const file = fileInputRef.current?.files?.[0];
    if (!file) {
      setStatus('Select a file first');
      return;
    }
    const projectedUsage = storageUsedBytes + file.size;
    if (projectedUsage > STORAGE_LIMIT_BYTES) {
      const overage = projectedUsage - STORAGE_LIMIT_BYTES;
      setStatus(`Storage limit reached (2 GB). Free up ${formatBytes(overage)} to upload.`);
      return;
    }
    const authHeaders = { Authorization: `Bearer ${session.token}` };
    const chunkSizeBytes = determineChunkSize(file.size);
    setPendingChunkSize(chunkSizeBytes);
    setIsUploading(true);
    setStatus('Planning upload...');
    setUploadProgress(0);

    try {
      const planResp = await fetch(`${BASE_URL}/plan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders },
        body: JSON.stringify({ file_name: file.name, file_size: file.size, chunk_size: chunkSizeBytes }),
      });
      if (!planResp.ok) throw new Error(`/plan -> ${planResp.status}`);
      const plan: UploadPlan = await planResp.json();
      const totalReplicaWrites = plan.placements.reduce((acc, placement) => acc + placement.replicas.length, 0);
      pushChunkLog(`Planned ${plan.placements.length} chunks (${totalReplicaWrites} replicas total)`);

      let completedWrites = 0;
      for (const placement of plan.placements) {
        const start = placement.chunk_index * plan.chunk_size;
        const end = Math.min(start + plan.chunk_size, file.size);
        const chunk = file.slice(start, end);

        for (const replica of placement.replicas) {
          setStatus(`Uploading chunk ${placement.chunk_index + 1}/${plan.placements.length}`);
          const form = new FormData();
          form.append('file_id', plan.file_id);
          form.append('chunk_id', placement.chunk_id);
          form.append('chunk_index', String(placement.chunk_index));
          form.append('node_id', replica.node_id);
          form.append('node_host', replica.host);
          form.append('node_port', String(replica.grpc_port));
          form.append('chunk', chunk, `${file.name}.part${placement.chunk_index}`);

          const uploadResp = await fetch(`${BASE_URL}/upload/chunk`, {
            method: 'POST',
            headers: authHeaders,
            body: form,
          });
          if (!uploadResp.ok) throw new Error(`/upload/chunk -> ${uploadResp.status}`);
          const uploadJson = (await uploadResp.json()) as UploadChunkResponse;
          if (!uploadJson.ok) throw new Error(uploadJson.reason || 'upload failed');

          completedWrites += 1;
          pushChunkLog(`Stored replica ${completedWrites}/${totalReplicaWrites}`);
          setUploadProgress(Math.round((completedWrites / totalReplicaWrites) * 100));
        }
      }

      const record: StoredUpload = {
        file_id: plan.file_id,
        file_name: file.name,
        file_size: file.size,
        chunk_size: plan.chunk_size,
        uploaded_at: Date.now(),
        favorite: false,
        trashed: false,
        last_accessed: Date.now(),
      };
      upsertUpload(record);
      setStatus('Upload complete');
      setUploadProgress(100);
      pushChunkLog(`Upload complete for ${file.name} (${plan.file_id})`);
    } catch (err: any) {
      console.error(err);
      setStatus(`Upload failed: ${err.message}`);
      pushChunkLog(`Upload failed: ${err.message}`);
      setUploadProgress(0);
    } finally {
      setIsUploading(false);
      setUploadProgress(0);
    }
  }, [upsertUpload, session, storageUsedBytes]);

  const resolveDownloadTarget = (query: string): StoredUpload | undefined => {
    const trimmed = query.trim();
    if (!trimmed) return undefined;
    const byId = uploads.find((u) => u.file_id === trimmed);
    if (byId) return byId;
    return uploads.find((u) => u.file_name.toLowerCase() === trimmed.toLowerCase());
  };

  const recordAccess = (fileId: string) => {
    updateUploads((prev) => prev.map((u) => (u.file_id === fileId ? { ...u, last_accessed: Date.now() } : u)));
  };

  const handleDownload = useCallback(
    async (fromRow?: StoredUpload) => {
      if (!session) {
        setStatus('Sign in to download');
        return;
      }
      const candidate = fromRow || resolveDownloadTarget(downloadQuery);
      if (!candidate) {
        setStatus('Enter a valid file name or id');
        return;
      }

      setIsDownloading(true);
      setStatus('Downloading...');
      setDownloadProgress(10);
      try {
        const resp = await fetch(`${BASE_URL}/download/${candidate.file_id}`, {
          headers: { Authorization: `Bearer ${session.token}` },
        });
        if (!resp.ok) throw new Error(`/download -> ${resp.status}`);
        const blob = await resp.blob();
        setDownloadProgress(75);
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = candidate.file_name || `${candidate.file_id}.bin`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        setStatus('Download complete');
        setDownloadProgress(100);
        recordAccess(candidate.file_id);
      } catch (err: any) {
        console.error(err);
        setStatus(`Download failed: ${err.message}`);
        setDownloadProgress(0);
      } finally {
        setIsDownloading(false);
      }
    },
    [downloadQuery, uploads, session]
  );

  const chunkSizeLabel = pendingChunkSize ? `${(pendingChunkSize / MB).toFixed(0)} MB auto` : 'auto based on file size';

  if (!session) {
    return (
      <div className="min-h-screen bg-[radial-gradient(circle_at_20%_20%,rgba(34,211,238,0.08),transparent_35%),radial-gradient(circle_at_80%_0%,rgba(251,191,36,0.08),transparent_40%),#070d1b] text-slate-100 flex items-center justify-center p-6">
        <div className="w-full max-w-md space-y-6 bg-slate-950/70 border border-slate-800 rounded-2xl p-6">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Phineas Cloud</p>
            <h1 className="text-3xl font-bold">Secure sign in</h1>
            <p className="text-sm text-slate-400">{authStatus}</p>
          </div>
          {!pendingChallenge && (
            <>
              <div className="flex justify-between items-center text-sm text-slate-400">
                <span>{authMode === 'login' ? 'Need an account?' : 'Already registered?'}</span>
                <button
                  type="button"
                  className="text-blue-400 hover:text-blue-200 font-medium"
                  onClick={() => {
                    const nextMode = authMode === 'login' ? 'signup' : 'login';
                    setAuthMode(nextMode);
                    setPendingChallenge(null);
                    setAuthError(null);
                    setOtpCode('');
                    setAuthStatus(nextMode === 'signup' ? 'Create your account' : 'Sign in to continue');
                  }}
                >
                  {authMode === 'login' ? 'Sign up' : 'Back to login'}
                </button>
              </div>

              <form
                className="space-y-4"
                onSubmit={authMode === 'login' ? handleLoginSubmit : handleSignupSubmit}
              >
                <div className="space-y-1">
                  <label className="text-sm text-slate-300">Email</label>
                  <input
                    className="input"
                    type="email"
                    value={authMode === 'login' ? loginForm.email : signupForm.email}
                    onChange={(e) =>
                      authMode === 'login'
                        ? setLoginForm((prev) => ({ ...prev, email: e.target.value }))
                        : setSignupForm((prev) => ({ ...prev, email: e.target.value }))
                    }
                    required
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-sm text-slate-300">Password</label>
                  <div className="flex items-center gap-2">
                    <input
                      className="input flex-1"
                      type={showPassword ? 'text' : 'password'}
                      value={authMode === 'login' ? loginForm.password : signupForm.password}
                      onChange={(e) =>
                        authMode === 'login'
                          ? setLoginForm((prev) => ({ ...prev, password: e.target.value }))
                          : setSignupForm((prev) => ({ ...prev, password: e.target.value }))
                      }
                      required
                    />
                    <button
                      type="button"
                      className="btn bg-slate-800 text-slate-200 whitespace-nowrap"
                      onClick={() => setShowPassword((v) => !v)}
                    >
                      {showPassword ? 'Hide' : 'Show'}
                    </button>
                  </div>
                </div>

                {authMode === 'signup' && (
                  <div className="space-y-1">
                    <label className="text-sm text-slate-300">Phone (for SMS OTP)</label>
                    <input
                      className="input"
                      type="tel"
                      value={signupForm.phone_number}
                      onChange={(e) => setSignupForm((prev) => ({ ...prev, phone_number: e.target.value }))}
                      placeholder="Optional"
                    />
                  </div>
                )}

                <div className="space-y-1">
                  <label className="text-sm text-slate-300">OTP channel</label>
                  <select
                    className="input"
                    value={authMode === 'login' ? loginForm.channel : signupForm.channel}
                    onChange={(e) => {
                      const channel = e.target.value as OtpChannel;
                      authMode === 'login'
                        ? setLoginForm((prev) => ({ ...prev, channel }))
                        : setSignupForm((prev) => ({ ...prev, channel }));
                    }}
                  >
                    <option value="email">Email</option>
                    <option value="sms">SMS</option>
                    <option value="both">Email + SMS</option>
                  </select>
                </div>

                <button className="btn w-full" type="submit" disabled={authBusy}>
                  {authBusy
                    ? 'Working…'
                    : authMode === 'login'
                      ? 'Send code'
                      : 'Sign up & send code'}
                </button>
                <p className="text-xs text-slate-500">Gateway: {BASE_URL}</p>
              </form>
            </>
          )}
          {pendingChallenge && (
            <form className="space-y-4" onSubmit={handleOtpVerify}>
              <div>
                <p className="text-sm text-slate-300">Enter the 6-digit code</p>
                <input
                  className="input tracking-[0.5em] text-center text-xl"
                  inputMode="numeric"
                  maxLength={6}
                  value={otpCode}
                  onChange={(e) => setOtpCode(e.target.value.replace(/[^0-9]/g, ''))}
                  required
                />
                <p className="text-xs text-slate-500 mt-2">Delivered via {pendingChallenge.channels.join(', ')}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button className="btn flex-1" type="submit" disabled={authBusy || otpCode.length !== 6}>
                  {authBusy ? 'Verifying…' : 'Verify code'}
                </button>
                <button className="btn bg-slate-800 text-slate-200" type="button" onClick={handleResendOtp} disabled={authBusy}>
                  Resend code
                </button>
                <button className="btn bg-slate-900/40 text-slate-300" type="button" onClick={resetAuthFlow}>
                  Use another account
                </button>
              </div>
            </form>
          )}
          {authError && <p className="text-sm text-rose-300">{authError}</p>}
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_20%_20%,rgba(34,211,238,0.08),transparent_35%),radial-gradient(circle_at_80%_0%,rgba(251,191,36,0.08),transparent_40%),#070d1b] text-slate-100">
      <div className="grid min-h-screen md:grid-cols-[260px_1fr]">
        <aside className="hidden md:flex flex-col gap-6 bg-slate-950/70 border-r border-slate-900/70 p-6">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Nexus</p>
            <h2 className="text-xl font-bold">Phineas Cloud</h2>
          </div>
          <nav className="space-y-2">
            {NAV_ITEMS.map((item) => (
              <button
                key={item.key}
                className={`w-full text-left px-3 py-2 rounded-lg border transition ${
                  activeTab === item.key
                    ? 'border-cyan-400 bg-slate-900 text-slate-100'
                    : 'border-transparent text-slate-400 hover:text-slate-100'
                }`}
                onClick={() => setActiveTab(item.key)}
              >
                {item.label}
              </button>
            ))}
          </nav>
          <div className="card space-y-2">
            <p className="text-xs uppercase text-slate-500">Storage used</p>
            <p className="text-2xl font-bold">{formatBytes(storageUsedBytes)}</p>
            <p className="text-sm text-slate-400">of {formatBytes(STORAGE_LIMIT_BYTES)} ({formatBytes(storageRemainingBytes)} left)</p>
            <div className="w-full h-2 rounded-full bg-slate-800 overflow-hidden">
              <div
                className="h-full bg-cyan-400"
                style={{ width: `${Math.min((storageUsedBytes / STORAGE_LIMIT_BYTES) * 100, 100)}%` }}
              ></div>
            </div>
            <p className="text-xs text-slate-500">Each account is capped at 2 GB.</p>
          </div>
        </aside>

        <div className="flex flex-col min-h-screen">
          <header className="sticky top-0 z-10 backdrop-blur bg-slate-900/70 border-b border-slate-800 px-6 py-4 flex flex-wrap items-center gap-4 justify-between">
            <div>
              <p className="text-xs uppercase tracking-wide text-slate-400">Phineas Cloud</p>
              <h1 className="text-3xl font-bold">Unified files, secure storage.</h1>
              <p className="text-slate-400 text-sm">Sync uploads, pin favorites, search everything.</p>
            </div>
            <div className="text-right text-sm text-slate-300 space-y-1">
              <p>{status}</p>
              <div className="flex flex-wrap items-center gap-3 text-xs text-slate-400 justify-end">
                <span>{session.user.email}</span>
                <button className="btn bg-slate-800 text-slate-200" onClick={handleLogout}>
                  Log out
                </button>
              </div>
            </div>
          </header>

          <main className="p-6 space-y-6">
            <section className="grid gap-4 lg:grid-cols-3">
              <div className="card">
                <p className="text-xs uppercase text-slate-400">Files synced</p>
                <p className="text-3xl font-bold">{nonTrashedUploads.length}</p>
              </div>
              <div className="card">
                <p className="text-xs uppercase text-slate-400">Favorites</p>
                <p className="text-3xl font-bold">{favoritesCount}</p>
              </div>
              <div className="card">
                <p className="text-xs uppercase text-slate-400">Trash</p>
                <p className="text-3xl font-bold">{uploads.filter((u) => u.trashed).length}</p>
              </div>
            </section>

            <section className="grid gap-4 lg:grid-cols-[2fr_1fr]">
              <div className="card space-y-4">
                <div className="flex flex-wrap gap-3 items-end">
                  <div className="flex-1 min-w-[220px]">
                    <p className="text-sm text-slate-300">Select file</p>
                    <input ref={fileInputRef} type="file" className="text-slate-200" onChange={handleFilePick} />
                  </div>
                  <div className="text-sm text-slate-400 min-w-[140px]">Chunk size: {chunkSizeLabel}</div>
                  <button className="btn" onClick={handleUpload} disabled={isUploading}>
                    {isUploading ? 'Uploading…' : 'Upload file'}
                  </button>
                </div>
                {isUploading && (
                  <div className="bg-slate-900/70 border border-slate-800 rounded-lg p-3 space-y-2">
                    <div className="flex items-center justify-between text-xs text-slate-400">
                      <span>Uploading chunks</span>
                      <span>{uploadProgress}%</span>
                    </div>
                    <div className="w-full h-2 rounded-full bg-slate-800 overflow-hidden">
                      <div
                        className="h-full bg-gradient-to-r from-cyan-400 via-blue-400 to-emerald-400 transition-all duration-300 animate-pulse"
                        style={{ width: `${uploadProgress}%` }}
                      ></div>
                    </div>
                    <p className="text-xs text-slate-500">{status}</p>
                  </div>
                )}
              </div>

              <div className="card space-y-3">
                <p className="text-sm text-slate-300">Download</p>
                <input
                  className="input"
                  value={downloadQuery}
                  onChange={(e) => setDownloadQuery(e.target.value)}
                  placeholder="File name or file id"
                />
                <button className="btn w-full" onClick={() => handleDownload()} disabled={isDownloading}>
                  {isDownloading ? 'Downloading…' : 'Download'}
                </button>
                <div className="w-full h-2 rounded-full bg-slate-900/60 border border-slate-800 overflow-hidden">
                  <div
                    className={`h-full bg-gradient-to-r from-emerald-400 to-cyan-400 transition-all duration-300 ${isDownloading ? 'animate-pulse' : ''}`}
                    style={{ width: `${downloadProgress}%` }}
                  ></div>
                </div>
              </div>
            </section>

            {activeTab === 'search' && (
              <section className="card space-y-3">
                <p className="text-xs uppercase text-slate-400">Search</p>
                <input
                  className="input"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Type to filter by name or id"
                />
              </section>
            )}

            <section className="card space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="text-xs uppercase text-slate-400">{NAV_ITEMS.find((n) => n.key === activeTab)?.label}</p>
                  <h2 className="text-lg font-semibold">{activeTab === 'trash' ? 'Trash bin' : 'Files'}</h2>
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="text-left text-slate-400 uppercase text-xs">
                      <th className="py-2 pr-3">File</th>
                      <th className="py-2 pr-3">Size</th>
                      <th className="py-2 pr-3">File ID</th>
                      <th className="py-2 pr-3">Uploaded</th>
                      <th className="py-2 pr-3">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredUploads.length === 0 && (
                      <tr>
                        <td colSpan={5} className="py-3 text-slate-400 text-center">No files yet</td>
                      </tr>
                    )}
                    {filteredUploads.map((u) => (
                      <tr key={u.file_id} className="border-t border-slate-800">
                        <td className="py-2 pr-3">
                          <div className="font-semibold">{u.file_name}</div>
                          <div className="text-xs text-slate-500">{u.favorite ? '★ Favorite' : ''}</div>
                        </td>
                        <td className="py-2 pr-3 text-slate-300">{formatBytes(u.file_size)}</td>
                        <td className="py-2 pr-3 text-slate-400 text-xs break-all">{u.file_id}</td>
                        <td className="py-2 pr-3 text-slate-400 text-xs">{new Date(u.uploaded_at).toLocaleString()}</td>
                        <td className="py-2 pr-3 space-x-2">
                          {!u.trashed && (
                            <>
                              <button className="btn" onClick={() => handleDownload(u)} disabled={isDownloading}>
                                Download
                              </button>
                              <button
                                className="btn bg-slate-800 text-slate-200"
                                onClick={() => toggleFavorite(u.file_id)}
                              >
                                {u.favorite ? 'Unfavorite' : 'Favorite'}
                              </button>
                              <button
                                className="btn bg-rose-500/20 text-rose-200"
                                onClick={() => moveToTrash(u.file_id, true)}
                              >
                                Trash
                              </button>
                            </>
                          )}
                          {u.trashed && (
                            <>
                              <button className="btn bg-emerald-500/20 text-emerald-200" onClick={() => moveToTrash(u.file_id, false)}>
                                Restore
                              </button>
                              <button className="btn bg-rose-600/30 text-rose-200" onClick={() => deleteForever(u.file_id)}>
                                Delete
                              </button>
                            </>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </main>
        </div>
      </div>
    </div>
  );
};

export default App;
