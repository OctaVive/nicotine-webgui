import { QueryClient, QueryObserver } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { clearSession } from './client';
import { connectLive } from './live';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  clearSession();
});

it('refetches an update arriving during a snapshot and cancels the streaming reader', async () => {
  vi.useFakeTimers();
  let stream!: ReadableStreamDefaultController<Uint8Array>;
  const cancelled = vi.fn();
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ cursor: 'instance:1', data: {} })))
    .mockResolvedValueOnce(
      new Response(
        new ReadableStream({
          start(c) {
            stream = c;
          },
          cancel: cancelled,
        }),
        { headers: { 'Content-Type': 'text/event-stream' } },
      ),
    );
  vi.stubGlobal('fetch', fetch);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let release!: (value: string) => void;
  const first = new Promise<string>((resolve) => {
    release = resolve;
  });
  const snapshot = vi.fn().mockReturnValueOnce(first).mockResolvedValue('fresh');
  const observer = new QueryObserver(client, { queryKey: ['api', '/downloads'], queryFn: snapshot });
  const unsubscribe = observer.subscribe(() => {});
  const stop = connectLive(client, () => {});
  await vi.advanceTimersByTimeAsync(0);
  stream.enqueue(
    new TextEncoder().encode('id: instance:2\nevent: downloads.updated\ndata: {"resource":"downloads"}\n\n'),
  );
  await vi.advanceTimersByTimeAsync(300);
  release('stale');
  await vi.advanceTimersByTimeAsync(0);
  expect(snapshot).toHaveBeenCalledTimes(2);
  expect(client.getQueryData(['api', '/downloads'])).toBe('fresh');
  stop();
  await vi.advanceTimersByTimeAsync(0);
  expect(cancelled).toHaveBeenCalled();
  unsubscribe();
  client.clear();
});

it('reconnects with the last event cursor instead of losing replay position', async () => {
  vi.useFakeTimers();
  let first!: ReadableStreamDefaultController<Uint8Array>;
  const second = new ReadableStream<Uint8Array>({ start() {} });
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ cursor: 'instance:1' })))
    .mockResolvedValueOnce(
      new Response(
        new ReadableStream({
          start(c) {
            first = c;
          },
        }),
        { headers: { 'Content-Type': 'text/event-stream' } },
      ),
    )
    .mockResolvedValueOnce(new Response(second, { headers: { 'Content-Type': 'text/event-stream' } }));
  vi.stubGlobal('fetch', fetch);
  const client = new QueryClient();
  const stop = connectLive(client, () => {});
  await vi.advanceTimersByTimeAsync(0);
  first.enqueue(new TextEncoder().encode('id: instance:7\nevent: status.updated\ndata: {}\n\n'));
  first.close();
  await vi.advanceTimersByTimeAsync(2100);
  expect(fetch.mock.calls[2][0]).toBe('/api/v1/events?cursor=instance%3A7');
  stop();
  client.clear();
});
