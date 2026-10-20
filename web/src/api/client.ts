import type { Envelope } from './types.gen';

const ENDPOINT_KEY = 'nicotine-endpoint';
const SESSION_KEY = 'nicotine-session';
const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]']);
let endpoint = '';
let csrf = '';
let sessionToken = '';
let generation = 0;
let controller = new AbortController();

function storage(kind: 'localStorage' | 'sessionStorage'): Storage | undefined {
  try {
    return typeof window === 'undefined' ? undefined : window[kind];
  } catch {
    return undefined;
  }
}
export function normalizeEndpoint(value: string): string {
  const url = new URL(value.trim());
  const sameOrigin = typeof window !== 'undefined' && url.origin === window.location.origin;
  const localHTTP =
    typeof window !== 'undefined' &&
    window.location.protocol === 'http:' &&
    LOOPBACK_HOSTS.has(window.location.hostname) &&
    LOOPBACK_HOSTS.has(url.hostname);
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' && (sameOrigin || localHTTP))) {
    throw new Error(
      'Use HTTPS for remote plugins. HTTP is supported only between a local HTTP GUI and a loopback plugin, or for the same-origin native UI.',
    );
  }
  if (url.username || url.password || url.search || url.hash)
    throw new Error('Plugin URL must not contain credentials, a query, or a fragment.');
  if (/%2f|%5c|%2e/i.test(url.pathname)) throw new Error('Use a plain plugin URL path.');
  return url.origin + url.pathname.replace(/\/api\/v1\/?$/, '').replace(/\/+$/, '');
}
function saveEndpoint() {
  storage('localStorage')?.setItem(ENDPOINT_KEY, endpoint);
}
function restore() {
  try {
    const saved = storage('localStorage')?.getItem(ENDPOINT_KEY);
    if (saved) endpoint = normalizeEndpoint(saved);
    const raw = storage('sessionStorage')?.getItem(SESSION_KEY);
    if (!raw) return;
    const session = JSON.parse(raw);
    if (
      session.endpoint === endpoint &&
      typeof session.session_token === 'string' &&
      typeof session.csrf === 'string' &&
      session.expires > Date.now() / 1000
    ) {
      sessionToken = session.session_token;
      csrf = session.csrf;
    } else storage('sessionStorage')?.removeItem(SESSION_KEY);
  } catch {
    storage('sessionStorage')?.removeItem(SESSION_KEY);
  }
}
restore();
export function getEndpoint() {
  return endpoint;
}
export function hasSession() {
  return !!sessionToken;
}
export function connectionGeneration() {
  return generation;
}
export function setCSRF(value: string) {
  csrf = value;
}
export function clearSession() {
  generation++;
  controller.abort();
  controller = new AbortController();
  sessionToken = '';
  csrf = '';
  storage('sessionStorage')?.removeItem(SESSION_KEY);
}
export function configureConnection(value: string) {
  const next = normalizeEndpoint(value);
  clearSession();
  endpoint = next;
  saveEndpoint();
}
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}
export function expireSession() {
  clearSession();
  if (typeof window !== 'undefined') window.dispatchEvent(new Event('session-expired'));
}
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const active = generation;
  const headers = new Headers(init.headers);
  if (sessionToken) headers.set('Authorization', 'Bearer ' + sessionToken);
  const method = init.method ?? 'GET';
  if (method !== 'GET') {
    headers.set('Content-Type', 'application/json');
    headers.set('X-CSRF-Token', csrf);
  }
  const signal = init.signal ? AbortSignal.any([controller.signal, init.signal]) : controller.signal;
  let response: Response;
  try {
    response = await fetch(endpoint + '/api/v1' + path, {
      ...init,
      method,
      headers,
      signal,
      redirect: 'error',
      credentials: endpoint ? 'omit' : 'same-origin',
    });
  } catch (error) {
    if (signal.aborted || (error as Error).name === 'AbortError') throw error;
    throw new Error(
      'Cannot reach the plugin. Check its URL, allowed Web GUI origin, and any reverse-proxy redirects. Remote plugins require HTTPS with a valid certificate.',
    );
  }
  if (active !== generation) throw new DOMException('Connection changed', 'AbortError');
  if (response.status === 401 && path !== '/auth/login') {
    expireSession();
    throw new ApiError(401, 'unauthenticated', 'Session expired. Please reconnect to the plugin.');
  }
  return response;
}
export async function request<T>(path: string, method = 'GET', body?: unknown): Promise<Envelope<T>> {
  const active = generation;
  const response = await apiFetch(path, {
    method,
    signal: AbortSignal.timeout(15000),
    body: method === 'GET' ? undefined : JSON.stringify(body ?? {}),
  });
  let value;
  try {
    value = await response.json();
  } catch {
    throw new Error('The plugin did not return JSON. Check the plugin URL and reverse-proxy configuration.');
  }
  if (path !== '/auth/login' && response.status !== 401 && active !== generation)
    throw new DOMException('Connection changed', 'AbortError');
  if (!response.ok)
    throw new ApiError(
      response.status,
      value.error?.code ?? 'request',
      value.error?.message ?? 'Request failed',
    );
  return value;
}
export async function login(value: string, token: string) {
  configureConnection(value);
  const active = generation;
  const response = await request<{ csrf: string; expires: number; session_token: string }>(
    '/auth/login',
    'POST',
    { token, mode: 'bearer' },
  );
  if (active !== generation) throw new DOMException('Connection changed', 'AbortError');
  if (
    typeof response.data.session_token !== 'string' ||
    !response.data.session_token ||
    typeof response.data.csrf !== 'string' ||
    typeof response.data.expires !== 'number' ||
    response.data.expires <= Date.now() / 1000
  )
    throw new Error('Upgrade the Nicotine+ plugin to a version with remote bearer sessions.');
  sessionToken = response.data.session_token;
  csrf = response.data.csrf;
  storage('sessionStorage')?.setItem(
    SESSION_KEY,
    JSON.stringify({ endpoint, session_token: sessionToken, csrf, expires: response.data.expires }),
  );
  return request<import('./models').Session>('/session');
}
export async function command<T = unknown>(path: string, method = 'POST', body?: unknown): Promise<T> {
  const active = generation;
  const response = await request<T & { command_id?: string }>(path, method, body);
  if (!response.data?.command_id) return response.data;
  for (let attempt = 0; attempt < 120; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 500));
    if (active !== generation) throw new DOMException('Connection changed', 'AbortError');
    const result = await request<{ state: string; result: T; error?: { code: string; message: string } }>(
      '/commands/' + response.data.command_id,
    );
    if (result.data.state === 'completed') return result.data.result;
    if (result.data.state === 'failed' || result.data.state === 'cancelled')
      throw new Error(result.data.error?.message ?? 'Command cancelled');
  }
  throw new Error('Command is still running. Refresh its resource before trying again.');
}
