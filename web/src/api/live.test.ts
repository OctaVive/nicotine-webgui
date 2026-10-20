import { QueryClient, QueryObserver } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { connectLive } from './live';

class FakeEventSource extends EventTarget {
  static latest: FakeEventSource;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor() {
    super();
    FakeEventSource.latest = this;
  }
  close() {}
}
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it('refetches when a live update arrives during the initial snapshot', async () => {
  vi.useFakeTimers();
  vi.stubGlobal('EventSource', FakeEventSource);
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(new Response(JSON.stringify({ cursor: 'instance:1', data: {} }))),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let release!: (value: string) => void;
  const first = new Promise<string>((resolve) => {
    release = resolve;
  });
  const fetchSnapshot = vi.fn().mockReturnValueOnce(first).mockResolvedValue('fresh');
  const observer = new QueryObserver(client, { queryKey: ['api', '/downloads'], queryFn: fetchSnapshot });
  const unsubscribe = observer.subscribe(() => {});
  const stop = connectLive(client, () => {});
  await vi.advanceTimersByTimeAsync(0);
  FakeEventSource.latest.dispatchEvent(
    new MessageEvent('downloads.updated', { data: JSON.stringify({ resource: 'downloads' }) }),
  );
  await vi.advanceTimersByTimeAsync(300);
  release('stale');
  await vi.advanceTimersByTimeAsync(0);
  expect(fetchSnapshot).toHaveBeenCalledTimes(2);
  expect(client.getQueryData(['api', '/downloads'])).toBe('fresh');
  stop();
  unsubscribe();
  client.clear();
});
