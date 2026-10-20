import type { QueryClient } from '@tanstack/react-query';
import { request } from './client';

export const EVENTS = [
  'status.updated',
  'downloads.updated',
  'uploads.updated',
  'rooms.updated',
  'private.updated',
  'available.updated',
  'searches.updated',
  'limits.updated',
  'buddies.updated',
  'interests.updated',
  'wishlist.updated',
  'shares.updated',
  'plugins.updated',
  'settings.updated',
  'statistics.updated',
  'search.results',
  'room.message',
  'private.message',
  'private.unread',
  'notification',
  'log',
  'browse.updated',
  'user.info',
  'shares.scan',
  'recommendations.updated',
];

export function connectLive(client: QueryClient, onState: (online: boolean) => void) {
  let closed = false;
  let stream: EventSource | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let batch: ReturnType<typeof setTimeout> | undefined;
  const deferred = new Set<string>();
  const affected = new Set<string>();
  let all = false;
  const unsubscribe = client.getQueryCache().subscribe((event) => {
    const query = event.query;
    if (query.state.fetchStatus === 'idle' && deferred.delete(query.queryHash) && !closed) {
      // An event arrived while this snapshot was in flight. Refetch after it
      // settles so a late snapshot cannot swallow the invalidation.
      queueMicrotask(() => {
        if (!closed) void client.invalidateQueries({ queryKey: query.queryKey, exact: true });
      });
    }
  });
  function flush() {
    batch = undefined;
    const resources = new Set(affected);
    affected.clear();
    const everything = all;
    all = false;
    for (const query of client.getQueryCache().findAll({ predicate: (q) => q.queryKey[0] === 'api' })) {
      const path = String(query.queryKey[1]).split('?')[0];
      const hit =
        everything ||
        [...resources].some((resource) => {
          const exact: Record<string, string> = {
            status: '/status',
            available: '/rooms/available',
            limits: '/transfers/limits',
            statistics: '/statistics',
            chat_commands: '/chat/commands',
          };
          const prefix = resource.startsWith('search/')
            ? '/searches/' + resource.slice(7)
            : resource.startsWith('room/')
              ? '/rooms/' + encodeURIComponent(resource.slice(5))
              : resource.startsWith('private/')
                ? '/private/' + encodeURIComponent(resource.slice(8))
                : resource.startsWith('browse/')
                  ? '/users/' + encodeURIComponent(resource.slice(7)) + '/browse'
                  : resource.startsWith('profile/')
                    ? '/users/' + encodeURIComponent(resource.slice(8))
                    : resource.startsWith('picture/')
                      ? '/users/' + encodeURIComponent(resource.slice(8)) + '/picture'
                      : (exact[resource] ?? '/' + resource);
          return path === prefix || path.startsWith(prefix + '/');
        });
      if (!hit) continue;
      if (query.state.fetchStatus === 'fetching') deferred.add(query.queryHash);
      else void client.invalidateQueries({ queryKey: query.queryKey, exact: true });
    }
  }
  const invalidate = (event?: Event) => {
    if (event instanceof MessageEvent) {
      try {
        const resource = JSON.parse(event.data).resource;
        if (resource) affected.add(resource);
        else all = true;
      } catch {
        all = true;
      }
    } else all = true;
    batch ??= setTimeout(flush, 250);
  };
  async function start() {
    try {
      // Establish a replay cursor before refetching snapshots. Events arriving during
      // the refetch invalidate those snapshots, and Query always reads final state.
      const snapshot = await request('/status');
      if (closed) return;
      stream = new EventSource('/api/v1/events?cursor=' + encodeURIComponent(snapshot.cursor));
      stream.onopen = () => {
        onState(true);
        invalidate();
      };
      stream.onerror = () => {
        onState(false);
        // A fresh session check distinguishes a server restart from expired auth.
        stream?.close();
        if (!closed) timer = setTimeout(start, 2000);
      };
      for (const name of EVENTS) stream.addEventListener(name, invalidate);
      stream.addEventListener('resync', invalidate);
    } catch {
      onState(false);
      if (!closed) timer = setTimeout(start, 2000);
    }
  }
  void start();
  return () => {
    closed = true;
    stream?.close();
    clearTimeout(timer);
    clearTimeout(batch);
    unsubscribe();
  };
}
