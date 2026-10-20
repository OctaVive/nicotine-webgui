export interface SSEFrame {
  event: string;
  data: string;
  id: string;
}

/** Read fetch-based SSE, including chunked UTF-8 and heartbeat comments. */
export async function readSSE(
  response: Response,
  onFrame: (frame: SSEFrame) => void,
  signal: AbortSignal,
  idleTimeout = 45_000,
): Promise<void> {
  if (!response.body) throw new Error('Event stream has no body');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let timedOut = false;
  let line = '';
  let afterCR = false;
  let event = '';
  let id = '';
  let data: string[] = [];
  const cancel = () => { void reader.cancel().catch(() => {}); };
  const resetTimer = () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      timedOut = true;
      cancel();
    }, idleTimeout);
  };
  function consumeLine(value: string) {
    if (value === '') {
      if (data.length) onFrame({ event: event || 'message', data: data.join('\n'), id });
      event = '';
      data = [];
      return;
    }
    if (value.startsWith(':')) return;
    const colon = value.indexOf(':');
    const field = colon < 0 ? value : value.slice(0, colon);
    let content = colon < 0 ? '' : value.slice(colon + 1);
    if (content.startsWith(' ')) content = content.slice(1);
    if (field === 'data') data.push(content);
    else if (field === 'event') event = content;
    else if (field === 'id' && !content.includes('\0')) id = content;
  }
  function consume(text: string) {
    for (const character of text) {
      if (afterCR && character === '\n') {
        afterCR = false;
        continue;
      }
      afterCR = character === '\r';
      if (character === '\r' || character === '\n') {
        consumeLine(line);
        line = '';
      } else line += character;
    }
  }
  signal.addEventListener('abort', cancel, { once: true });
  try {
    if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
    resetTimer();
    while (true) {
      const { done, value } = await reader.read();
      if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
      if (timedOut) throw new Error('Event stream idle timeout');
      if (done) {
        consume(decoder.decode());
        return;
      }
      resetTimer();
      consume(decoder.decode(value, { stream: true }));
    }
  } finally {
    clearTimeout(timer);
    signal.removeEventListener('abort', cancel);
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
