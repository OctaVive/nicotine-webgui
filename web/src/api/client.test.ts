import { afterEach, describe, expect, it, vi } from 'vitest';
import { clearSession, command, request, setCSRF } from './client';

afterEach(() => {
  clearSession();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
describe('API commands', () => {
  it('sends CSRF and credentials without exposing the login token', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ ok: true, data: {} }), { status: 200 }));
    vi.stubGlobal('fetch', fetch);
    setCSRF('csrf-value');
    await request('/away', 'POST', { away: true });
    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/away',
      expect.objectContaining({
        credentials: 'same-origin',
        headers: expect.any(Headers),
        redirect: 'error',
      }),
    );
    expect(fetch.mock.calls[0][1].headers.get('X-CSRF-Token')).toBe('csrf-value');
  });
  it('polls a started command instead of submitting it twice', async () => {
    vi.useFakeTimers();
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: { command_id: 'one' } }), { status: 202 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ data: { state: 'completed', result: { token: 7 } } }), { status: 200 }),
      );
    vi.stubGlobal('fetch', fetch);
    const result = command('/searches', 'POST', { term: 'ambient' });
    await vi.advanceTimersByTimeAsync(600);
    expect(await result).toEqual({ token: 7 });
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch.mock.calls[1][0]).toBe('/api/v1/commands/one');
  });
});
