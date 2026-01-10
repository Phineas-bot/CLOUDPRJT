export type OtpChannel = 'email' | 'sms' | 'both';

export type AuthUser = {
  user_id: string;
  email: string;
  phone_number?: string | null;
  otp_channels?: string[] | null;
  created_at?: number;
};

export type AuthSession = {
  token: string;
  token_type: string;
  expires_at: number;
  user: AuthUser;
};

export type PendingChallenge = {
  pending_token: string;
  channels: string[];
  expires_in: number;
};

export type LoginPayload = {
  email: string;
  password: string;
  channel?: OtpChannel;
};

export type ResendPayload = {
  pending_token: string;
  channel?: OtpChannel;
};

export type VerifyPayload = {
  pending_token: string;
  code: string;
};

export type SignupPayload = {
  email: string;
  password: string;
  phone_number?: string;
  channel?: OtpChannel;
};

export type AdminSignupPayload = {
  email: string;
  password: string;
};

const parseSession = (dto: { access_token: string; token_type: string; expires_in: number; user: AuthUser }): AuthSession => ({
  token: dto.access_token,
  token_type: dto.token_type,
  expires_at: Date.now() + dto.expires_in * 1000,
  user: dto.user,
});

const readJson = async <T>(resp: Response): Promise<T> => {
  if (!resp.ok) {
    const message = await resp.text();
    throw new Error(message || `Request failed with status ${resp.status}`);
  }
  return resp.json() as Promise<T>;
};

export async function login(baseUrl: string, payload: LoginPayload): Promise<PendingChallenge> {
  const resp = await fetch(`${baseUrl}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return readJson<PendingChallenge>(resp);
}

export async function resendOtp(baseUrl: string, payload: ResendPayload): Promise<PendingChallenge> {
  const resp = await fetch(`${baseUrl}/auth/otp/resend`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return readJson<PendingChallenge>(resp);
}

export async function verifyOtp(baseUrl: string, payload: VerifyPayload): Promise<AuthSession> {
  const resp = await fetch(`${baseUrl}/auth/otp/verify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await readJson<{ access_token: string; token_type: string; expires_in: number; user: AuthUser }>(resp);
  return parseSession(data);
}

export async function fetchMe(baseUrl: string, token: string): Promise<AuthUser> {
  const resp = await fetch(`${baseUrl}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return readJson<AuthUser>(resp);
}

export async function signup(baseUrl: string, payload: SignupPayload): Promise<PendingChallenge> {
  const resp = await fetch(`${baseUrl}/auth/signup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return readJson<PendingChallenge>(resp);
}

export async function adminLogin(baseUrl: string, payload: LoginPayload): Promise<AuthSession> {
  const resp = await fetch(`${baseUrl}/admin/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await readJson<{ access_token: string; token_type: string; expires_in: number; user: AuthUser }>(resp);
  return parseSession(data);
}

export async function adminSignup(baseUrl: string, payload: AdminSignupPayload): Promise<AuthSession> {
  const resp = await fetch(`${baseUrl}/admin/auth/signup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await readJson<{ access_token: string; token_type: string; expires_in: number; user: AuthUser }>(resp);
  return parseSession(data);
}

export function loadSession(key: string): AuthSession | null {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as AuthSession;
    return parsed.token && parsed.expires_at > Date.now() ? parsed : null;
  } catch (err) {
    console.warn('session load failed', err);
    return null;
  }
}

export function saveSession(key: string, session: AuthSession | null): void {
  if (!session) {
    localStorage.removeItem(key);
    return;
  }
  localStorage.setItem(key, JSON.stringify(session));
}
