import type { Envelope } from './types.gen';

let csrf = '';
export function setCSRF(value: string) {
  csrf = value;
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

export async function request<T>(path: string, method = 'GET', body?: unknown): Promise<Envelope<T>> {
  const response = await fetch('/api/v1' + path, {
    method,
    credentials: 'same-origin',
    headers: { ...(method === 'GET' ? {} : { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }) },
    body: method === 'GET' ? undefined : JSON.stringify(body ?? {}),
  });
  const value = await response.json();
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event('session-expired'));
    throw new ApiError(
      response.status,
      value.error?.code ?? 'request',
      value.error?.message ?? 'Request failed',
    );
  }
  return value;
}

export async function command<T = unknown>(path: string, method = 'POST', body?: unknown): Promise<T> {
  const response = await request<T & { command_id?: string }>(path, method, body);
  if (!response.data?.command_id) return response.data;
  // Do not repeat a mutation if the main thread has already started it.
  for (let attempt = 0; attempt < 120; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 500));
    const result = await request<{ state: string; result: T; error?: { code: string; message: string } }>(
      '/commands/' + response.data.command_id,
    );
    if (result.data.state === 'completed') return result.data.result;
    if (result.data.state === 'failed' || result.data.state === 'cancelled')
      throw new Error(result.data.error?.message ?? 'Command cancelled');
  }
  throw new Error('Command is still running. Refresh its resource before trying again.');
}
