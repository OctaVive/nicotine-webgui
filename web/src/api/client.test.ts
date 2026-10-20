import { afterEach, describe, expect, it, vi } from 'vitest';
import { clearSession, command, normalizeEndpoint, request, setCSRF } from './client';

afterEach(() => {
  clearSession();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
describe('plugin endpoint transport', () => {
  function openGUI(origin: string) {
    vi.stubGlobal('window', { location: new URL(origin) });
  }

  it('allows local HTTP plugins on different ports and loopback hostnames', () => {
    openGUI('http://127.0.0.1:8180');
    for (const host of ['127.0.0.1', 'localhost', '[::1]']) {
      expect(normalizeEndpoint(`http://${host}:8181/`)).toBe(`http://${host}:8181`);
    }
    openGUI('http://localhost:8180');
    expect(normalizeEndpoint('http://127.0.0.1:8181')).toBe('http://127.0.0.1:8181');
  });

  it('still rejects remote and lookalike HTTP hosts', () => {
    openGUI('http://127.0.0.1:8180');
    for (const host of [
      '192.168.1.10',
      'example.com',
      'localhost.example.com',
      '127.0.0.1.example.com',
      '0.0.0.0',
    ]) {
      expect(() => normalizeEndpoint(`http://${host}:8181`)).toThrow('Use HTTPS');
    }
  });

  it('does not allow remote pages or HTTPS pages to use loopback HTTP', () => {
    for (const origin of ['http://example.com', 'https://example.com', 'https://localhost:8180']) {
      openGUI(origin);
      expect(() => normalizeEndpoint('http://127.0.0.1:8181')).toThrow('Use HTTPS');
    }
  });

  it('retains HTTPS and same-origin native HTTP support', () => {
    openGUI('http://example.com:8181');
    expect(normalizeEndpoint('http://example.com:8181/')).toBe('http://example.com:8181');
    expect(normalizeEndpoint('https://nicotine.example.com/api/v1/')).toBe('https://nicotine.example.com');
  });

  it('continues rejecting credentials and non-HTTP protocols', () => {
    openGUI('http://localhost:8180');
    expect(() => normalizeEndpoint('http://user:password@localhost:8181')).toThrow('credentials');
    expect(() => normalizeEndpoint('ftp://localhost:8181')).toThrow('Use HTTPS');
  });
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
