import { useEffect, useState } from 'react';
import { Link, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import * as Dialog from '@radix-ui/react-dialog';
import { clearSession, getEndpoint, hasSession, login, request, setCSRF } from '../api/client';
import { connectLive } from '../api/live';
import type { Session, Status } from '../api/models';
import { useLayout } from '../stores/layout';
import { Feedback, bytes, useAction, useAPI } from './hooks';
import { SearchPage, TransfersPage } from '../features/transfers';
import { ChatPage } from '../features/chat';
import {
  PeoplePage,
  BrowsePage,
  SharesPage,
  PluginsPage,
  SettingsPage,
  ActivityPage,
} from '../features/extras';

const NAV = [
  ['/search', '⌕', 'Search'],
  ['/downloads', '↓', 'Downloads'],
  ['/uploads', '↑', 'Uploads'],
  ['/rooms', '◫', 'Rooms'],
  ['/private', '✉', 'Private chat'],
  ['/buddies', '♧', 'Buddies'],
  ['/browse', '▤', 'Browse'],
  ['/interests', '◇', 'Discovery'],
  ['/shares', '▧', 'Shares'],
  ['/plugins', '⊞', 'Plugins'],
  ['/stats', '▥', 'Statistics'],
  ['/settings', '⚙', 'Settings'],
];

export function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [checking, setChecking] = useState(true);
  const [online, setOnline] = useState(false);
  const [feedback, setFeedback] = useState<{ message: string; error: boolean } | null>(null);
  const [palette, setPalette] = useState(false);
  const client = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const layout = useLayout();
  useEffect(() => {
    let live = true;
    (getEndpoint() && hasSession()
      ? request<Session>('/session')
      : Promise.reject(new Error('Not connected'))
    )
      .then((result) => {
        if (live) {
          setCSRF(result.data.csrf);
          setSession(result.data);
        }
      })
      .catch(() => {})
      .finally(() => {
        if (live) setChecking(false);
      });
    const expired = () => {
      setSession(null);
      clearSession();
      setOnline(false);
      client.clear();
    };
    window.addEventListener('session-expired', expired);
    return () => {
      live = false;
      window.removeEventListener('session-expired', expired);
    };
  }, [client]);
  useEffect(() => (session ? connectLive(client, setOnline) : undefined), [session, client]);
  useEffect(() => {
    document.documentElement.dataset.theme = layout.theme;
    document.documentElement.dataset.density = layout.density;
  }, [layout.theme, layout.density]);
  useEffect(() => {
    function shortcut(e: KeyboardEvent) {
      const editing = (e.target as HTMLElement)?.matches('input,textarea,[contenteditable]');
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setPalette((p) => !p);
      }
      if (e.altKey && /^[1-9]$/.test(e.key)) {
        e.preventDefault();
        navigate(NAV[Number(e.key) - 1][0]);
      }
      if (e.key === '/' && !editing) {
        e.preventDefault();
        navigate('/search');
        setTimeout(() => document.querySelector<HTMLInputElement>('[name=search]')?.focus(), 0);
      }
    }
    window.addEventListener('keydown', shortcut);
    return () => window.removeEventListener('keydown', shortcut);
  }, [navigate]);
  useEffect(() => {
    if (/^\/(search|rooms|private|browse|users)\/.+/.test(location.pathname)) {
      const label = decodeURIComponent(location.pathname.split('/').slice(2).join('/'));
      layout.open(location.pathname, label);
    }
  }, [location.pathname]);
  if (checking)
    return (
      <div className="login">
        <p>Connecting to Nicotine Web…</p>
      </div>
    );
  if (!session)
    return (
      <Login
        onLogin={(value) => {
          client.clear();
          useLayout.setState({ tabs: [] });
          setSession(value);
          setCSRF(value.csrf);
          navigate('/search');
        }}
      />
    );
  return (
    <Feedback.Provider value={(message, error = false) => setFeedback({ message, error })}>
      <div className="shell">
        <header className="topbar">
          <Link className="brand" to="/search">
            <span className="brand-mark">
              n<span>+</span>
            </span>
            <span>
              nicotine<span className="muted"> / web</span>
            </span>
          </Link>
          <div className="top-actions">
            <button className="quiet" onClick={() => setPalette(true)}>
              Jump to… <kbd>⌘ K</kbd>
            </button>
            <StatusBar />
            <Link to="/notifications" aria-label="Notifications">
              ♧
            </Link>
            <button
              className="quiet"
              onClick={async () => {
                let timeout: ReturnType<typeof setTimeout> | undefined;
                try {
                  await Promise.race([
                    request('/auth/logout', 'POST'),
                    new Promise((resolve) => {
                      timeout = setTimeout(resolve, 1500);
                    }),
                  ]);
                } catch {
                  // A disconnected plugin must not prevent choosing another host.
                } finally {
                  clearTimeout(timeout);
                  clearSession();
                  setSession(null);
                  setOnline(false);
                  client.clear();
                  useLayout.setState({ tabs: [] });
                  setFeedback(null);
                  navigate('/login');
                }
              }}
            >
              Log out / change connection
            </button>
          </div>
        </header>
        <aside className="sidebar">
          <div className="sidebar-label">WORKSPACE</div>
          <nav>
            {NAV.map(([path, icon, label], i) => (
              <NavLink key={path} to={path}>
                <span className="nav-icon">{icon}</span>
                {label}
                <kbd>{i < 9 ? i + 1 : ''}</kbd>
              </NavLink>
            ))}
          </nav>
          <div className="sidebar-bottom">
            <span className={'dot ' + (online ? 'green' : 'amber')} />
            {online ? 'Live bridge' : 'Reconnecting…'}
            <small>
              v{session.version} · Nicotine+ {session.nicotine_version}
            </small>
          </div>
        </aside>
        <main>
          {!online && (
            <div className="banner" role="status">
              Bridge connection interrupted. Reconnecting automatically; actions may be unavailable.
            </div>
          )}
          {layout.tabs.length > 0 && (
            <div className="workspace-tabs">
              {layout.tabs.map((tab) => (
                <div key={tab.path} className={tab.path === location.pathname ? 'active' : ''}>
                  <Link to={tab.path}>{tab.label}</Link>
                  <button
                    aria-label={'Close ' + tab.label}
                    onClick={() => {
                      layout.close(tab.path);
                      if (tab.path === location.pathname) navigate('/' + tab.path.split('/')[1]);
                    }}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          )}
          {feedback && (
            <div
              role={feedback.error ? 'alert' : 'status'}
              className={'toast ' + (feedback.error ? 'error' : '')}
            >
              {feedback.message}
              <button aria-label="Dismiss notification" onClick={() => setFeedback(null)}>
                ×
              </button>
            </div>
          )}
          <Routes>
            <Route path="/search/:token?" element={<SearchPage />} />
            <Route path="/downloads" element={<TransfersPage kind="downloads" />} />
            <Route path="/uploads" element={<TransfersPage kind="uploads" />} />
            <Route path="/rooms/:name?" element={<ChatPage kind="rooms" />} />
            <Route path="/private/:name?" element={<ChatPage kind="private" />} />
            <Route path="/browse/:name?" element={<BrowsePage />} />
            <Route path="/users/:name" element={<PeoplePage kind="profile" />} />
            <Route path="/buddies" element={<PeoplePage kind="buddies" />} />
            <Route path="/interests" element={<PeoplePage kind="interests" />} />
            <Route path="/shares" element={<SharesPage />} />
            <Route path="/plugins" element={<PluginsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/notifications" element={<ActivityPage kind="notifications" />} />
            <Route path="/logs" element={<ActivityPage kind="logs" />} />
            <Route path="/stats" element={<ActivityPage kind="statistics" />} />
            <Route path="*" element={<SearchPage />} />
          </Routes>
        </main>
        <footer>
          <span>LOCAL COMPANION</span>
          <span>
            Files stay on your Nicotine+ host · <Link to="/logs">View logs</Link>
          </span>
        </footer>
      </div>
      <Dialog.Root open={palette} onOpenChange={setPalette}>
        <Dialog.Portal>
          <Dialog.Overlay className="overlay" />
          <Dialog.Content className="dialog">
            <Dialog.Title>Jump to workspace</Dialog.Title>
            <Dialog.Description>
              Choose a section. Alt + 1–9 switches the first nine sections.
            </Dialog.Description>
            {NAV.map(([path, icon, label]) => (
              <button
                key={path}
                onClick={() => {
                  navigate(path);
                  setPalette(false);
                }}
              >
                {icon} {label}
              </button>
            ))}
            <Dialog.Close>Close</Dialog.Close>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </Feedback.Provider>
  );
}

function Login({ onLogin }: { onLogin: (session: Session) => void }) {
  const [endpoint, setEndpoint] = useState(getEndpoint());
  const [token, setToken] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  return (
    <div className="login">
      <div className="login-card">
        <span className="brand-mark">
          n<span>+</span>
        </span>
        <p className="eyebrow">YOUR SOULSEEK WORKSPACE</p>
        <h1>Welcome to Nicotine Web.</h1>
        <p className="muted">Connect to your existing Nicotine+ client through its bridge plugin.</p>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setPending(true);
            setError('');
            try {
              const session = await login(endpoint, token);
              setToken('');
              onLogin(session.data);
            } catch (err) {
              setError((err as Error).message);
            } finally {
              setPending(false);
            }
          }}
        >
          <label>
            Plugin URL
            <input
              type="url"
              autoFocus
              disabled={pending}
              autoComplete="url"
              value={endpoint}
              onChange={(e) => setEndpoint(e.target.value)}
              required
              placeholder="https://nicotine.example.com"
            />
          </label>
          <label>
            Access token
            <input
              type="password"
              disabled={pending}
              autoComplete="current-password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              required
              placeholder="Enter your bridge token"
            />
          </label>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button className="primary" disabled={pending}>
            {pending ? 'Connecting…' : 'Open workspace →'}
          </button>
        </form>
        <small>
          Find the access token in the plugin preferences on your Nicotine+ host. That plugin must allow this
          Web GUI’s origin: {window.location.origin}.
        </small>
      </div>
    </div>
  );
}

function StatusBar() {
  const { data } = useAPI<Status>('/status');
  const action = useAction();
  return (
    <div className="connection">
      <span className={'dot ' + (data?.connected ? 'green' : 'amber')} />
      <span>{data?.connected ? data.username : 'Disconnected'}</span>
      <span className="speeds">
        ↓ {bytes(data?.download_speed)}/s · ↑ {bytes(data?.upload_speed)}/s
      </span>
      {data?.connected && (
        <button
          className="quiet"
          onClick={() => void action('/away', 'POST', { away: !data.away }).catch(() => {})}
        >
          {data.away ? 'Away' : 'Online'}
        </button>
      )}
      <button
        className="quiet"
        onClick={() => void action(data?.connected ? '/disconnect' : '/connect').catch(() => {})}
      >
        {data?.connected ? 'Disconnect' : 'Connect'}
      </button>
    </div>
  );
}
