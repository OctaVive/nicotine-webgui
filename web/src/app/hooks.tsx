import { createContext, useContext } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { command, connectionGeneration } from '../api/client';

export function useAPI<T>(path: string) {
  return useQuery({ queryKey: ['api', path], queryFn: () => command<T>(path, 'GET') });
}
export const Feedback = createContext<(message: string, error?: boolean) => void>(() => {});
export function useAction() {
  const client = useQueryClient();
  const notify = useContext(Feedback);
  return async <T,>(path: string, method = 'POST', body?: unknown): Promise<T | undefined> => {
    const active = connectionGeneration();
    try {
      const data = await command<T>(path, method, body);
      if (active !== connectionGeneration()) throw new DOMException('Connection changed', 'AbortError');
      await client.invalidateQueries({ predicate: (q) => q.queryKey[0] === 'api' });
      return data;
    } catch (error) {
      if ((error as Error).name !== 'AbortError') notify((error as Error).message, true);
      throw error;
    }
  };
}
export function bytes(value = 0): string {
  if (value < 1024) return Math.round(value) + ' B';
  const units = ['KiB', 'MiB', 'GiB', 'TiB'];
  let i = -1;
  do {
    value /= 1024;
    i++;
  } while (value >= 1024 && i < units.length - 1);
  return value.toFixed(1) + ' ' + units[i];
}
export function Loading({ error, loading }: { error: Error | null; loading: boolean }) {
  if (error)
    return (
      <p role="alert" className="error">
        {error.message}
      </p>
    );
  if (loading) return <p className="empty">Loading…</p>;
  return null;
}
