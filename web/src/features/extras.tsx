import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import type { Buddy, FileRow, Log, Notice, Plugin, Results, Share } from '../api/models';
import { DataTable } from '../components/DataTable';
import { bytes, Loading, useAction, useAPI } from '../app/hooks';
import { useLayout } from '../stores/layout';
import { fileColumns } from './transfers';

function FolderTree({
  rows,
  selected,
  onSelect,
}: {
  rows: FileRow[];
  selected: string;
  onSelect: (path: string) => void;
}) {
  const [expanded, setExpanded] = useState(new Set<string>());
  const children = new Map<string, Set<string>>();
  for (const row of rows) {
    const parts = row.virtual_path.split('\\').slice(0, -1).slice(0, 32);
    let parent = '';
    for (const part of parts) {
      const path = parent ? parent + '\\' + part : part;
      if (!children.has(parent)) children.set(parent, new Set());
      children.get(parent)!.add(path);
      parent = path;
    }
  }
  function render(parent: string, depth: number): React.ReactNode {
    return [...(children.get(parent) ?? [])].sort().map((path) => (
      <div key={path}>
        <div
          className={'folder-row ' + (path === selected ? 'active' : '')}
          style={{ paddingLeft: depth * 12 + 8 }}
        >
          <button
            aria-label={'Expand ' + path}
            onClick={() => {
              const next = new Set(expanded);
              if (next.has(path)) next.delete(path);
              else next.add(path);
              setExpanded(next);
            }}
          >
            {children.has(path) ? (expanded.has(path) ? '▾' : '▸') : '·'}
          </button>
          <button role="treeitem" aria-selected={path === selected} onClick={() => onSelect(path)}>
            ▧ {path.split('\\').at(-1)}
          </button>
        </div>
        {expanded.has(path) && render(path, depth + 1)}
      </div>
    ));
  }
  return (
    <aside className="folder-tree" role="tree" aria-label="Shared folders">
      <button onClick={() => onSelect('')}>All folders</button>
      {render('', 0)}
    </aside>
  );
}

function PluginSettings({ name }: { name: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(!open)}>Settings</button>
      {open && <PluginSettingsForm name={name} />}
    </>
  );
}

function PluginSettingsForm({ name }: { name: string }) {
  const query = useAPI<
    Record<
      string,
      { value: string | number | boolean; description: string; type: string; choices?: string[] }
    >
  >('/plugins/' + encodeURIComponent(name) + '/settings');
  const action = useAction();
  return (
    <div className="plugin-settings">
      <Loading error={query.error} loading={query.isLoading} />
      <p className="muted">
        Numeric, boolean, and enumerated settings are available. Edit other values on the host.
      </p>
      {Object.entries(query.data ?? {}).map(([key, field]) => (
        <label className="setting-row" key={key}>
          {field.description}
          {typeof field.value === 'boolean' ? (
            <input
              type="checkbox"
              checked={field.value}
              onChange={(e) =>
                void action('/plugins/' + encodeURIComponent(name) + '/settings', 'PATCH', {
                  [key]: e.target.checked,
                }).catch(() => {})
              }
            />
          ) : field.choices ? (
            <select
              value={String(field.value)}
              onChange={(e) =>
                void action('/plugins/' + encodeURIComponent(name) + '/settings', 'PATCH', {
                  [key]: e.target.value,
                }).catch(() => {})
              }
            >
              {field.choices.map((choice) => (
                <option key={choice}>{choice}</option>
              ))}
            </select>
          ) : (
            <input
              type={typeof field.value === 'number' ? 'number' : 'text'}
              defaultValue={field.value}
              onBlur={(e) => {
                const value = typeof field.value === 'number' ? Number(e.target.value) : e.target.value;
                if (value !== field.value)
                  void action('/plugins/' + encodeURIComponent(name) + '/settings', 'PATCH', {
                    [key]: value,
                  }).catch(() => {});
              }}
            />
          )}
        </label>
      ))}
    </div>
  );
}

export function BrowsePage() {
  const { name } = useParams();
  const navigate = useNavigate();
  const action = useAction();
  const [user, setUser] = useState('');
  const [filter, setFilter] = useState('');
  const [selected, setSelected] = useState(new Set<string>());
  const [folder, setFolder] = useState('');
  const query = useAPI<Results>(
    name ? '/users/' + encodeURIComponent(name) + '/browse?limit=10000' : '/users/_/browse',
  );
  const all = query.data?.items ?? [];
  const rows = all.filter(
    (r) =>
      (!folder || r.virtual_path.startsWith(folder + '\\')) &&
      r.virtual_path.toLowerCase().includes(filter.toLowerCase()),
  );
  return (
    <section>
      <div className="page-heading">
        <div>
          <p className="eyebrow">EXPLORE A COLLECTION</p>
          <h1>Browse shares</h1>
          <p className="muted">Explore a user’s shared files by folder.</p>
        </div>
      </div>
      <form
        className="panel toolbar"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            await action('/users/' + encodeURIComponent(user) + '/browse');
            navigate('/browse/' + encodeURIComponent(user));
          } catch {}
        }}
      >
        <input
          aria-label="Browse username"
          placeholder="Username"
          value={user}
          onChange={(e) => setUser(e.target.value)}
          required
        />
        <button className="primary">Browse user</button>
      </form>
      {name && (
        <div className="panel">
          <div className="toolbar">
            <h2>{name}</h2>
            <button
              onClick={() => void action('/users/' + encodeURIComponent(name) + '/browse').catch(() => {})}
            >
              Refresh
            </button>
            <input
              aria-label="Filter folders"
              placeholder="Filter folders or files…"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
          </div>
          <Loading loading={query.isLoading} error={query.error} />
          {query.data?.truncated && <p className="banner">Collection exceeds the bridge retention limit.</p>}
          <div className="browse-layout">
            <FolderTree rows={all} selected={folder} onSelect={setFolder} />
            <DataTable rows={rows} columns={fileColumns} selected={selected} onSelect={setSelected} />
          </div>
          <div className="table-footer">
            <span>{rows.length} files</span>
            <button
              disabled={!folder}
              onClick={() =>
                void action('/users/' + encodeURIComponent(name) + '/folder-downloads', 'POST', {
                  virtual_path: folder,
                }).catch(() => {})
              }
            >
              Download folder
            </button>
            <button
              className="primary"
              disabled={!selected.size}
              onClick={async () => {
                try {
                  await action('/users/' + encodeURIComponent(name) + '/downloads', 'POST', {
                    ids: [...selected],
                  });
                  setSelected(new Set());
                } catch {}
              }}
            >
              ↓ Download selected
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

export function PeoplePage({ kind }: { kind: 'profile' | 'buddies' | 'interests' }) {
  const { name } = useParams();
  const action = useAction();
  const [entry, setEntry] = useState('');
  const buddies = useAPI<Buddy[]>('/buddies');
  const interests = useAPI<{ likes: string[]; dislikes: string[] }>('/interests');
  const wishlist = useAPI<string[]>('/wishlist');
  const recommendations = useAPI<Record<string, Record<string, number>>>('/recommendations');
  const picture = useAPI<{ data_url: string }>(
    name ? '/users/' + encodeURIComponent(name) + '/picture' : '/users/_/picture',
  );
  const profile = useAPI<{ username: string; description: string; slots: number; queue: number }>(
    name ? '/users/' + encodeURIComponent(name) : '/users/_',
  );
  if (kind === 'profile')
    return (
      <section>
        <div className="page-heading">
          <div>
            <p className="eyebrow">COMMUNITY</p>
            <h1>{name}</h1>
          </div>
          <button
            onClick={() => void action('/users/' + encodeURIComponent(name!) + '/refresh').catch(() => {})}
          >
            Request profile
          </button>
        </div>
        <div className="panel profile">
          <p className="muted">Profiles load after a request to the user.</p>
          <Loading error={profile.error} loading={profile.isLoading} />
          <div className="profile-picture">
            {picture.data?.data_url && <img src={picture.data.data_url} alt={name + ' profile'} />}
          </div>
          <p className="description">{profile.data?.description || 'No profile received yet.'}</p>
          <div className="toolbar">
            <span>Upload slots: {profile.data?.slots ?? '—'}</span>
            <span>Queue: {profile.data?.queue ?? '—'}</span>
          </div>
          <div className="toolbar">
            <Link
              className="button"
              to={'/browse/' + encodeURIComponent(name!)}
              onClick={() => void action('/users/' + encodeURIComponent(name!) + '/browse').catch(() => {})}
            >
              Browse files
            </Link>
            <Link className="button" to={'/private/' + encodeURIComponent(name!)}>
              Message
            </Link>
            <button onClick={() => void action('/buddies', 'POST', { username: name }).catch(() => {})}>
              Add buddy
            </button>
            {['ignore', 'unignore', 'ban', 'unban'].map((verb) => (
              <button
                key={verb}
                onClick={() =>
                  void action('/users/' + encodeURIComponent(name!) + '/' + verb).catch(() => {})
                }
              >
                {verb}
              </button>
            ))}
          </div>
        </div>
      </section>
    );
  if (kind === 'buddies')
    return (
      <section>
        <div className="page-heading">
          <div>
            <p className="eyebrow">YOUR PEOPLE</p>
            <h1>Buddies</h1>
          </div>
        </div>
        <form
          className="panel toolbar"
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              await action('/buddies', 'POST', { username: entry });
              setEntry('');
            } catch {}
          }}
        >
          <input
            aria-label="Buddy username"
            placeholder="Username"
            value={entry}
            onChange={(e) => setEntry(e.target.value)}
            required
          />
          <button className="primary">Add buddy</button>
        </form>
        <Loading loading={buddies.isLoading} error={buddies.error} />
        <div className="card-grid">
          {buddies.data?.map((b) => (
            <div className="panel person" key={b.username}>
              <h2>
                <Link to={'/users/' + encodeURIComponent(b.username)}>{b.username}</Link>
              </h2>
              <input
                aria-label={'Note for ' + b.username}
                defaultValue={b.note}
                placeholder="Add a note…"
                onBlur={(e) => {
                  if (e.target.value !== b.note)
                    void action('/buddies/' + encodeURIComponent(b.username), 'PATCH', {
                      note: e.target.value,
                    }).catch(() => {});
                }}
              />
              {[
                ['notify', b.notify_status],
                ['trusted', b.is_trusted],
                ['prioritized', b.is_prioritized],
              ].map(([key, checked]) => (
                <label key={String(key)} className="check-label">
                  <input
                    type="checkbox"
                    checked={Boolean(checked)}
                    onChange={(e) =>
                      void action('/buddies/' + encodeURIComponent(b.username), 'PATCH', {
                        [String(key)]: e.target.checked,
                      }).catch(() => {})
                    }
                  />
                  {key}
                </label>
              ))}
              <div className="toolbar">
                <Link to={'/private/' + encodeURIComponent(b.username)}>Message</Link>
                <button
                  onClick={() =>
                    void action('/buddies/' + encodeURIComponent(b.username), 'DELETE').catch(() => {})
                  }
                >
                  Remove
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>
    );
  return (
    <section>
      <div className="page-heading">
        <div>
          <p className="eyebrow">FOLLOW YOUR CURIOSITY</p>
          <h1>Discovery</h1>
          <p className="muted">Shape recommendations and keep a wishlist.</p>
        </div>
        <button onClick={() => void action('/recommendations').catch(() => {})}>
          Refresh recommendations
        </button>
      </div>
      <div className="card-grid">
        {(['likes', 'dislikes', 'wishlist'] as const).map((category) => (
          <div className="panel person" key={category}>
            <h2>{category}</h2>
            <form
              className="toolbar"
              onSubmit={async (e) => {
                e.preventDefault();
                const form = e.currentTarget;
                const value = String(new FormData(form).get('item'));
                try {
                  await action(
                    category === 'wishlist' ? '/wishlist' : '/interests/' + category,
                    'POST',
                    category === 'wishlist' ? { term: value } : { item: value },
                  );
                  form.reset();
                } catch {}
              }}
            >
              <input aria-label={'Add ' + category} name="item" required placeholder="Add an item…" />
              <button>+</button>
            </form>
            {(category === 'wishlist' ? wishlist.data : interests.data?.[category])?.map((item) => (
              <div className="list-row" key={item}>
                {item}
                <button
                  aria-label={'Remove ' + item}
                  onClick={() =>
                    void action(
                      category === 'wishlist'
                        ? '/wishlist/' + encodeURIComponent(item)
                        : '/interests/' + category,
                      'DELETE',
                      { item },
                    ).catch(() => {})
                  }
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        ))}
      </div>
      <div className="panel person">
        <h2>Recommendations</h2>
        {Object.entries(recommendations.data?.recommendations ?? {}).map(([item, score]) => (
          <div className="list-row" key={item}>
            <span>{item}</span>
            <span className="muted">{score}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

export function SharesPage() {
  const query = useAPI<Share[]>('/shares');
  const scan = useAPI<{ state: string }>('/shares/status');
  const action = useAction();
  return (
    <section>
      <div className="page-heading">
        <div>
          <p className="eyebrow">GIVE SOMETHING BACK</p>
          <h1>Shared folders</h1>
          <p className="muted">Paths refer to directories on the Nicotine+ host.</p>
        </div>
        <div className="toolbar">
          <button onClick={() => void action('/shares/rebuild').catch(() => {})}>Rebuild</button>
          <button className="primary" onClick={() => void action('/shares/rescan').catch(() => {})}>
            Rescan shares
          </button>
        </div>
      </div>
      <p role="status" className="muted">
        {scan.data?.state ?? 'No scan in progress'}
      </p>
      <form
        className="panel toolbar"
        onSubmit={async (e) => {
          e.preventDefault();
          const form = e.currentTarget;
          const data = new FormData(form);
          try {
            await action('/shares', 'POST', {
              path: data.get('path'),
              name: data.get('name') || undefined,
              permission: data.get('permission'),
            });
            form.reset();
          } catch {}
        }}
      >
        <input name="path" aria-label="Host share path" placeholder="/absolute/path/on/host" required />
        <input name="name" aria-label="Virtual share name" placeholder="Virtual name (optional)" />
        <select name="permission" aria-label="Share permission">
          <option>public</option>
          <option>buddy</option>
          <option>trusted</option>
        </select>
        <button className="primary">Add share</button>
      </form>
      <Loading loading={query.isLoading} error={query.error} />
      <div className="panel person">
        {query.data?.map((s) => (
          <div key={s.id} className="list-row">
            <div>
              <strong>{s.id}</strong>
              <p className="muted">{s.path}</p>
            </div>
            <span className="pill">{s.permission}</span>
            <button
              onClick={() => void action('/shares/' + encodeURIComponent(s.id), 'DELETE').catch(() => {})}
            >
              Remove
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}

export function PluginsPage() {
  const query = useAPI<Plugin[]>('/plugins');
  const action = useAction();
  return (
    <section>
      <div className="page-heading">
        <div>
          <p className="eyebrow">EXTEND YOUR CLIENT</p>
          <h1>Plugins</h1>
          <p className="muted">The web bridge manages other installed plugins.</p>
        </div>
      </div>
      <Loading loading={query.isLoading} error={query.error} />
      <div className="panel person">
        {query.data?.map((p) => (
          <div className="list-row" key={p.name}>
            <strong>{p.name}</strong>
            <span className="pill">{p.enabled ? 'Enabled' : 'Disabled'}</span>
            {p.protected ? (
              <span className="muted">Serving this interface</span>
            ) : (
              <div>
                {(p.enabled ? ['disable', 'reload'] : ['enable']).map((verb) => (
                  <button
                    key={verb}
                    onClick={() =>
                      void action('/plugins/' + encodeURIComponent(p.name), 'POST', { action: verb }).catch(
                        () => {},
                      )
                    }
                  >
                    {verb}
                  </button>
                ))}
                {p.enabled && <PluginSettings name={p.name} />}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

export function SettingsPage() {
  const bridge = useAPI<Record<string, unknown>>('/bridge/settings');
  const settings = useAPI<Record<string, Record<string, number | boolean>>>('/settings');
  const action = useAction();
  const layout = useLayout();
  return (
    <section>
      <div className="page-heading">
        <div>
          <p className="eyebrow">MAKE IT YOURS</p>
          <h1>Settings</h1>
        </div>
      </div>
      <div className="card-grid">
        <div className="panel person">
          <h2>Appearance</h2>
          <div className="toolbar">
            <button onClick={layout.toggleTheme}>Theme: {layout.theme}</button>
            <button onClick={layout.toggleDensity}>Density: {layout.density}</button>
          </div>
          <h2>Client preferences</h2>
          {Object.entries(settings.data ?? {}).map(([section, values]) =>
            Object.entries(values).map(([key, value]) => (
              <label className="setting-row" key={section + key}>
                {key}
                {typeof value === 'boolean' ? (
                  <input
                    type="checkbox"
                    checked={value}
                    onChange={(e) =>
                      void action('/settings', 'PATCH', { [section]: { [key]: e.target.checked } }).catch(
                        () => {},
                      )
                    }
                  />
                ) : (
                  <input
                    type="number"
                    min="0"
                    max="1440"
                    defaultValue={value}
                    onBlur={(e) =>
                      void action('/settings', 'PATCH', {
                        [section]: { [key]: Number(e.target.value) },
                      }).catch(() => {})
                    }
                  />
                )}
              </label>
            )),
          )}
        </div>
        <div className="panel person">
          <h2>Bridge configuration</h2>
          <p className="muted">
            Read-only. Change these in plugin preferences or container environment variables, then restart the
            bridge.
          </p>
          {Object.entries(bridge.data ?? {}).map(([key, value]) => (
            <div className="list-row" key={key}>
              <span>{key}</span>
              <code>{String(value)}</code>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export function ActivityPage({ kind }: { kind: 'notifications' | 'logs' | 'statistics' }) {
  const notices = useAPI<Notice[]>('/notifications');
  const logs = useAPI<Log[]>('/logs');
  const stats = useAPI<Record<string, number>>('/statistics');
  const action = useAction();
  const [filter, setFilter] = useState('');
  return (
    <section>
      <div className="page-heading">
        <div>
          <p className="eyebrow">CLIENT ACTIVITY</p>
          <h1>{kind === 'statistics' ? 'Statistics' : kind === 'logs' ? 'Logs' : 'Notifications'}</h1>
        </div>
        {kind === 'notifications' && (
          <button onClick={() => void action('/notifications/read').catch(() => {})}>Mark all read</button>
        )}
      </div>
      {kind === 'statistics' ? (
        <div className="summary-grid">
          {Object.entries(stats.data ?? {}).map(([key, value]) => (
            <div className="panel metric" key={key}>
              <span>{key.replaceAll('_', ' ')}</span>
              <strong>{key.includes('size') ? bytes(value) : value.toLocaleString()}</strong>
            </div>
          ))}
        </div>
      ) : (
        <div className="panel person">
          <input
            aria-label="Filter activity"
            placeholder="Filter activity…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          {(kind === 'logs' ? (logs.data ?? []) : (notices.data ?? []))
            .filter((n) => n.message.toLowerCase().includes(filter.toLowerCase()))
            .slice()
            .reverse()
            .map((n, i) => (
              <div key={i} className="list-row">
                <time className="muted">{new Date(n.ts * 1000).toLocaleTimeString()}</time>
                <p>{n.message}</p>
              </div>
            ))}
        </div>
      )}
    </section>
  );
}
