import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import type { History, Room } from '../api/models';
import { Loading, useAction, useAPI } from '../app/hooks';

export function ChatPage({ kind }: { kind: 'rooms' | 'private' }) {
  const { name } = useParams();
  const navigate = useNavigate();
  const action = useAction();
  const [target, setTarget] = useState('');
  const [message, setMessage] = useState('');
  const [pending, setPending] = useState(false);
  const listing = useAPI<Room[]>('/' + kind);
  const available = useAPI<string[]>('/rooms/available');
  const unread = useAPI<Record<string, number>>('/unread');
  const commands = useAPI<string[]>('/chat/commands');
  const history = useAPI<History>(
    name ? '/' + kind + '/' + encodeURIComponent(name) + '/messages?limit=500' : '/' + kind,
  );
  const messages = name && !Array.isArray(history.data) ? (history.data?.items ?? []) : [];
  const room = listing.data?.find((r) => r.name === name);
  const bottom = useRef<HTMLDivElement>(null);
  const last = messages.at(-1)?.id ?? 0;
  useEffect(() => {
    if (name) void action('/' + kind + '/' + encodeURIComponent(name) + '/history').catch(() => {});
  }, [name, kind]);
  useEffect(() => {
    if (name && document.visibilityState === 'visible' && last) {
      void action('/' + kind + '/' + encodeURIComponent(name) + '/read', 'POST', { through: last }).catch(
        () => {},
      );
      bottom.current?.scrollIntoView({ block: 'nearest' });
    }
  }, [name, kind, last]);
  useEffect(() => {
    const visible = () => {
      if (name && last && document.visibilityState === 'visible')
        void action('/' + kind + '/' + encodeURIComponent(name) + '/read', 'POST', { through: last }).catch(
          () => {},
        );
    };
    document.addEventListener('visibilitychange', visible);
    return () => document.removeEventListener('visibilitychange', visible);
  }, [name, kind, last]);
  async function send() {
    if (!name || !message.trim() || pending) return;
    setPending(true);
    try {
      const base = '/' + kind + '/' + encodeURIComponent(name);
      if (kind === 'rooms' && message.startsWith('/')) {
        const [command, ...args] = message.slice(1).split(' ');
        await action(base + '/commands', 'POST', { command, args: args.join(' ') });
      } else await action(base + '/messages', 'POST', { message });
      setMessage('');
    } catch {
    } finally {
      setPending(false);
    }
  }
  return (
    <section>
      <div className="page-heading">
        <div>
          <p className="eyebrow">STAY IN THE CONVERSATION</p>
          <h1>{kind === 'rooms' ? 'Rooms' : 'Private chat'}</h1>
          <p className="muted">
            {kind === 'rooms'
              ? 'Find your people. Share what you’re listening to.'
              : 'Your conversations, all in one place.'}
          </p>
        </div>
      </div>
      <div className="panel chat-layout">
        <aside className="conversation-list">
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                if (kind === 'rooms') await action('/rooms', 'POST', { name: target });
                navigate('/' + kind + '/' + encodeURIComponent(target));
                setTarget('');
              } catch {}
            }}
          >
            <input
              aria-label={kind === 'rooms' ? 'Room name' : 'Username'}
              list={kind === 'rooms' ? 'available-rooms' : undefined}
              placeholder={kind === 'rooms' ? 'Find or join a room…' : 'Start a conversation…'}
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              required
            />
            <button aria-label="Open conversation">+</button>
          </form>
          <datalist id="available-rooms">
            {available.data?.slice(0, 1000).map((r) => (
              <option key={r} value={r} />
            ))}
          </datalist>
          <Loading loading={listing.isLoading} error={listing.error} />
          {listing.data?.map((r) => (
            <Link
              className={r.name === name ? 'active' : ''}
              key={r.name}
              to={'/' + kind + '/' + encodeURIComponent(r.name)}
            >
              <span>
                {kind === 'rooms' ? '# ' : '◉ '}
                {r.name}
              </span>
              {(unread.data?.[(kind === 'rooms' ? 'room/' : 'private/') + r.name] ?? 0) > 0 && (
                <span className="badge">
                  {unread.data?.[(kind === 'rooms' ? 'room/' : 'private/') + r.name]}
                </span>
              )}
            </Link>
          ))}
        </aside>
        <div className="conversation">
          {!name ? (
            <div className="empty">
              <span className="large-icon">{kind === 'rooms' ? '◫' : '✉'}</span>
              <h2>Pick a conversation.</h2>
              <p>Open a room or enter a username to get started.</p>
            </div>
          ) : (
            <>
              <div className="toolbar">
                <h2>
                  {kind === 'rooms' ? '# ' : ''}
                  {name}
                </h2>
                <span className="muted">
                  {kind === 'rooms' ? `${room?.users?.length ?? 0} people` : 'Private conversation'}
                </span>
                {kind === 'rooms' ? (
                  <button
                    onClick={() =>
                      void action('/rooms/' + encodeURIComponent(name), 'DELETE')
                        .then(() => navigate('/rooms'))
                        .catch(() => {})
                    }
                  >
                    Leave room
                  </button>
                ) : (
                  <>
                    <Link to={'/users/' + encodeURIComponent(name)}>Profile</Link>
                    <button
                      onClick={() =>
                        void action('/users/' + encodeURIComponent(name) + '/ignore').catch(() => {})
                      }
                    >
                      Ignore
                    </button>
                  </>
                )}
              </div>
              <div className="messages" role="log" aria-label="Messages">
                <Loading loading={history.isLoading} error={history.error} />
                {!Array.isArray(history.data) && history.data?.truncated && (
                  <p className="hint">Older messages have reached the retention limit.</p>
                )}
                <p className="history-note">History includes messages received since the bridge started.</p>
                {messages.map((row) => (
                  <article key={row.id} className={row.outgoing ? 'outgoing' : ''}>
                    <div className="avatar">{(row.user || '?').slice(0, 1).toUpperCase()}</div>
                    <div>
                      <div className="message-meta">
                        <Link to={'/users/' + encodeURIComponent(row.user || '')}>{row.user}</Link>
                        <time>
                          {new Date(row.ts * 1000).toLocaleTimeString([], {
                            hour: '2-digit',
                            minute: '2-digit',
                          })}
                        </time>
                      </div>
                      <p>{row.message}</p>
                    </div>
                  </article>
                ))}
                <div ref={bottom} />
              </div>
              <div className="command-suggestions">
                {kind === 'rooms' &&
                  message.startsWith('/') &&
                  !message.includes(' ') &&
                  commands.data
                    ?.filter((c) => c.startsWith(message))
                    .slice(0, 8)
                    .map((c) => (
                      <button key={c} onClick={() => setMessage(c.trim() + ' ')}>
                        {c}
                      </button>
                    ))}
              </div>
              <form
                className="composer"
                onSubmit={(e) => {
                  e.preventDefault();
                  void send();
                }}
              >
                <textarea
                  aria-label="Message"
                  placeholder={'Message ' + name + '…'}
                  value={message}
                  maxLength={4000}
                  onChange={(e) => setMessage(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                      e.preventDefault();
                      void send();
                    }
                  }}
                />
                <div>
                  <small>Ctrl / ⌘ + Enter to send</small>
                  <button className="primary" disabled={pending || !message.trim()}>
                    {pending ? 'Sending…' : 'Send →'}
                  </button>
                </div>
              </form>
            </>
          )}
        </div>
        {kind === 'rooms' && room && (
          <aside className="room-users">
            <div className="sidebar-label">IN THIS ROOM</div>
            {room.users?.map((u) => (
              <Link key={u.username} to={'/users/' + encodeURIComponent(u.username)}>
                <span className={'dot ' + (u.status ? 'green' : 'amber')} />
                {u.username}
              </Link>
            ))}
            {Object.entries(room.tickers ?? {}).map(([user, ticker]) => (
              <p key={user} className="ticker">
                <strong>{user}</strong> {ticker}
              </p>
            ))}
          </aside>
        )}
      </div>
    </section>
  );
}
