import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import type { ColumnDef } from '@tanstack/react-table';
import { DataTable } from '../components/DataTable';
import type { FileRow, Results, Search, Transfer } from '../api/models';
import { bytes, Loading, useAction, useAPI } from '../app/hooks';

export const fileColumns: ColumnDef<FileRow, any>[] = [
  {
    accessorKey: 'virtual_path',
    header: 'File / Folder',
    size: 480,
    cell: ({ getValue }) => <span title={getValue()}>{getValue()}</span>,
  },
  { accessorKey: 'size', header: 'Size', size: 110, cell: ({ getValue }) => bytes(getValue()) },
  {
    accessorKey: 'username',
    header: 'User',
    size: 150,
    cell: ({ getValue }) => <Link to={'/users/' + encodeURIComponent(getValue())}>{getValue()}</Link>,
  },
  { accessorKey: 'speed', header: 'Speed', size: 120, cell: ({ getValue }) => bytes(getValue()) + '/s' },
  {
    accessorKey: 'bitrate',
    header: 'Bitrate',
    size: 100,
    cell: ({ getValue }) => (getValue() ? getValue() + ' kbps' : '—'),
  },
];

export function SearchPage() {
  const { token } = useParams();
  const navigate = useNavigate();
  const action = useAction();
  const [term, setTerm] = useState('');
  const [mode, setMode] = useState('global');
  const [target, setTarget] = useState('');
  const [filter, setFilter] = useState('');
  const [selected, setSelected] = useState(new Set<string>());
  const [pending, setPending] = useState(false);
  useEffect(() => {
    setSelected(new Set());
  }, [token]);
  const searches = useAPI<Search[]>('/searches');
  const results = useAPI<Results>(token ? '/searches/' + token + '?limit=10000' : '/searches');
  const rows = token && !Array.isArray(results.data) ? (results.data?.items ?? []) : [];
  const filtered = useMemo(
    () => rows.filter((r) => (r.virtual_path + r.username).toLowerCase().includes(filter.toLowerCase())),
    [rows, filter],
  );
  const current = searches.data?.find((s) => String(s.token) === token);
  return (
    <section>
      <div className="page-heading">
        <div>
          <h1>Search</h1>
        </div>
        <span className="pill">{searches.data?.length ?? 0} open searches</span>
      </div>
      <form
        className="search-form panel"
        onSubmit={async (e) => {
          e.preventDefault();
          setPending(true);
          try {
            const result = await action<{ token: number }>('/searches', 'POST', {
              term,
              mode,
              room: mode === 'rooms' ? target : undefined,
              users: mode === 'user' ? target.split(',').map((s) => s.trim()) : undefined,
            });
            if (result) {
              setSelected(new Set());
              navigate('/search/' + result.token);
            }
          } catch {
          } finally {
            setPending(false);
          }
        }}
      >
        <span className="search-symbol">⌕</span>
        <input
          name="search"
          aria-label="Search term"
          placeholder="Search files…"
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          required
        />
        <select aria-label="Search mode" value={mode} onChange={(e) => setMode(e.target.value)}>
          <option value="global">Global network</option>
          <option value="rooms">Room</option>
          <option value="buddies">Buddies</option>
          <option value="user">User</option>
        </select>
        {(mode === 'rooms' || mode === 'user') && (
          <input
            aria-label="Search target"
            placeholder={mode === 'rooms' ? 'Room name' : 'Users, comma separated'}
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            required
          />
        )}
        <button className="primary" disabled={pending}>
          {pending ? 'Searching…' : 'Search network →'}
        </button>
      </form>
      <div className="resource-tabs">
        {searches.data?.map((search) => (
          <div key={search.token} className={String(search.token) === token ? 'active' : ''}>
            <Link onClick={() => setSelected(new Set())} to={'/search/' + search.token}>
              {search.term}
            </Link>
            <button
              aria-label={'Close search ' + search.term}
              onClick={() =>
                void action('/searches/' + search.token, 'DELETE')
                  .then(() => {
                    if (String(search.token) === token) navigate('/search');
                  })
                  .catch(() => {})
              }
            >
              ×
            </button>
          </div>
        ))}
      </div>
      {!token ? (
        <div className="welcome panel">
          <span className="large-icon">⌕</span>
          <h2>Search files on Soulseek</h2>
          <p className="muted">Enter a search term above to find files shared by other users.</p>
          <div className="hint">
            Tip <kbd>/</kbd> focuses search from anywhere.
          </div>
        </div>
      ) : (
        <div className="panel results-panel">
          <div className="toolbar">
            <h2>{current?.term ?? 'Search results'}</h2>
            <span className="muted">
              {filtered.length.toLocaleString()} files · {new Set(rows.map((r) => r.username)).size} users
            </span>
            <input
              aria-label="Filter results"
              placeholder="Filter these results…"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
          </div>
          <Loading loading={results.isLoading} error={results.error} />
          {!Array.isArray(results.data) && results.data?.truncated && (
            <p className="banner">Result limit reached. Showing the newest retained files.</p>
          )}
          <DataTable rows={filtered} columns={fileColumns} selected={selected} onSelect={setSelected} />
          <div className="table-footer">
            <span>{selected.size} selected</span>
            <button
              disabled={!selected.size || pending}
              onClick={async () => {
                setPending(true);
                try {
                  await action('/searches/' + token + '/folder-downloads', 'POST', { ids: [...selected] });
                } catch {
                } finally {
                  setPending(false);
                }
              }}
            >
              Download folders
            </button>
            <button
              className="primary"
              disabled={!selected.size || pending}
              onClick={async () => {
                setPending(true);
                try {
                  await action('/searches/' + token + '/downloads', 'POST', { ids: [...selected] });
                  setSelected(new Set());
                } catch {
                } finally {
                  setPending(false);
                }
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

export function TransfersPage({ kind }: { kind: 'downloads' | 'uploads' }) {
  const query = useAPI<Transfer[]>('/' + kind);
  const limits = useAPI<Record<string, string | number | boolean>>('/transfers/limits');
  const action = useAction();
  const [filter, setFilter] = useState('');
  const [status, setStatus] = useState('all');
  const [selected, setSelected] = useState(new Set<string>());
  const [pending, setPending] = useState(false);
  const [showLimits, setShowLimits] = useState(false);
  const [denial, setDenial] = useState('');
  const all = query.data ?? [];
  const rows = all.filter(
    (r) =>
      (status === 'all' || r.status === status) &&
      (r.virtual_path + r.username).toLowerCase().includes(filter.toLowerCase()),
  );
  const base = fileColumns as ColumnDef<Transfer, any>[];
  const columns: ColumnDef<Transfer, any>[] = [
    base[0],
    {
      accessorKey: 'status',
      header: 'STATUS',
      size: 150,
      cell: ({ getValue }) => (
        <span className={'state state-' + String(getValue()).toLowerCase().replaceAll(' ', '-')}>
          {getValue()}
        </span>
      ),
    },
    {
      id: 'progress',
      header: 'PROGRESS',
      size: 180,
      cell: ({ row }) => (
        <div className="progress-cell">
          <progress value={row.original.current_byte_offset || 0} max={row.original.size || 1} />
          <small>
            {bytes(row.original.current_byte_offset)} / {bytes(row.original.size)}
          </small>
        </div>
      ),
    },
    base[2],
    base[3],
    { accessorKey: 'queue_position', header: 'QUEUE', size: 85 },
    {
      accessorKey: 'time_left',
      header: 'ETA',
      size: 90,
      cell: ({ getValue }) => (getValue() ? Math.ceil(getValue() / 60) + ' min' : '—'),
    },
  ];
  return (
    <section>
      <div className="page-heading">
        <div>
          <p className="eyebrow">TRANSFER WORKSPACE</p>
          <h1>{kind === 'downloads' ? 'Downloads' : 'Uploads'}</h1>
          <p className="muted">Keep an eye on every file, from queue to completion.</p>
        </div>
        <button onClick={() => setShowLimits(!showLimits)}>Bandwidth & slots</button>
      </div>
      <div className="summary-grid">
        {[
          ['Total files', all.length],
          ['Transferring', all.filter((r) => r.status === 'Transferring').length],
          ['Queued', all.filter((r) => r.status === 'Queued').length],
          ['Current speed', bytes(all.reduce((sum, r) => sum + (r.speed || 0), 0)) + '/s'],
        ].map(([label, value]) => (
          <div key={label} className="panel metric">
            <span>{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
      </div>
      {showLimits && (
        <div className="panel limits">
          <h2>Bandwidth limits</h2>
          <p className="muted">Speed limits are in KiB/s. Changes apply immediately.</p>
          {limits.data &&
            Object.entries(limits.data).map(([key, value]) => (
              <label key={key}>
                {key.replaceAll('_', ' ')}
                {typeof value === 'boolean' ? (
                  <input
                    type="checkbox"
                    checked={value}
                    onChange={(e) =>
                      void action('/transfers/limits', 'PATCH', { [key]: e.target.checked }).catch(() => {})
                    }
                  />
                ) : typeof value === 'string' ? (
                  <select
                    value={value}
                    onChange={(e) =>
                      void action('/transfers/limits', 'PATCH', { [key]: e.target.value }).catch(() => {})
                    }
                  >
                    {['unlimited', 'primary', 'alternative'].map((v) => (
                      <option key={v}>{v}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    key={key + value}
                    type="number"
                    min="0"
                    max="10000000"
                    defaultValue={value}
                    onBlur={(e) => {
                      if (Number(e.target.value) !== value)
                        void action('/transfers/limits', 'PATCH', { [key]: Number(e.target.value) }).catch(
                          () => {},
                        );
                    }}
                  />
                )}
              </label>
            ))}
        </div>
      )}
      <div className="panel">
        <div className="toolbar">
          <select aria-label="Transfer status" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="all">All statuses</option>
            {[...new Set(all.map((r) => r.status))].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
          <input
            aria-label="Filter transfers"
            placeholder="Filter files or users…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>
        <Loading loading={query.isLoading} error={query.error} />
        <DataTable rows={rows} columns={columns} selected={selected} onSelect={setSelected} />
        <div className="table-footer">
          <span>{selected.size} selected</span>
          {kind === 'uploads' && (
            <input
              aria-label="Upload denial reason"
              placeholder="Reason for denial…"
              value={denial}
              onChange={(e) => setDenial(e.target.value)}
            />
          )}
          {(kind === 'downloads'
            ? ['pause', 'resume', 'retry', 'cancel', 'clear']
            : ['retry', 'cancel', 'clear', 'deny']
          ).map((verb) => (
            <button
              key={verb}
              disabled={!selected.size || pending || (verb === 'deny' && !denial.trim())}
              onClick={async () => {
                setPending(true);
                try {
                  await action('/' + kind + '/actions', 'POST', {
                    ids: [...selected],
                    action: verb,
                    message: denial,
                  });
                  setSelected(new Set());
                } catch {
                } finally {
                  setPending(false);
                }
              }}
            >
              {verb}
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
