import { afterEach, expect, it, vi } from 'vitest';
import { readSSE, type SSEFrame } from './sse';

afterEach(() => vi.useRealTimers());

it('parses split UTF-8, multiline data, CRLF, comments, and persistent IDs', async () => {
  const bytes = new TextEncoder().encode(
    ': heartbeat\r\nid: instance:7\r\nevent: update\r\ndata: café\r\ndata: next\r\n\r\ndata: last\n\n',
  );
  const frames: SSEFrame[] = [];
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const byte of bytes) controller.enqueue(Uint8Array.of(byte));
      controller.close();
    },
  });
  await readSSE(new Response(body), (frame) => frames.push(frame), new AbortController().signal);
  expect(frames).toEqual([
    { event: 'update', data: 'café\nnext', id: 'instance:7' },
    { event: 'message', data: 'last', id: 'instance:7' },
  ]);
});

it('does not dispatch an unfinished event at EOF', async () => {
  const frame = vi.fn();
  await readSSE(new Response('data: unfinished\n'), frame, new AbortController().signal);
  expect(frame).not.toHaveBeenCalled();
});

it('cancels a pending reader when aborted', async () => {
  const cancel = vi.fn();
  const abort = new AbortController();
  const reading = readSSE(new Response(new ReadableStream({ cancel })), vi.fn(), abort.signal);
  const result = expect(reading).rejects.toMatchObject({ name: 'AbortError' });
  abort.abort();
  await result;
  expect(cancel).toHaveBeenCalled();
});

it('resets the idle timeout on heartbeat bytes and cancels stalled streams', async () => {
  vi.useFakeTimers();
  let stream!: ReadableStreamDefaultController<Uint8Array>;
  const cancel = vi.fn();
  const body = new ReadableStream<Uint8Array>({
    start(controller) { stream = controller; },
    cancel,
  });
  const reading = readSSE(new Response(body), vi.fn(), new AbortController().signal, 100);
  const result = expect(reading).rejects.toThrow('idle timeout');
  await vi.advanceTimersByTimeAsync(80);
  stream.enqueue(new TextEncoder().encode(': heartbeat\n\n'));
  await vi.advanceTimersByTimeAsync(80);
  expect(cancel).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(21);
  await result;
  expect(cancel).toHaveBeenCalled();
});
