import { useEffect, useMemo, useRef, useState } from 'react';
import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from '@tanstack/react-table';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useLayout } from '../stores/layout';

export function DataTable<T extends { id: string }>({
  rows,
  columns,
  selected,
  onSelect,
}: {
  rows: T[];
  columns: ColumnDef<T, any>[];
  selected?: Set<string>;
  onSelect?: (ids: Set<string>) => void;
}) {
  const viewport = useRef<HTMLDivElement>(null);
  const [sorting, setSorting] = useState<SortingState>([]);
  const [focus, setFocus] = useState(0);
  const density = useLayout((s) => s.density);
  const rowHeight = density === 'compact' ? 38 : 46;
  const definitions = useMemo(
    () =>
      onSelect
        ? [
            {
              id: 'select',
              size: 42,
              enableSorting: false,
              header: () => (
                <input
                  aria-label="Select all rows"
                  type="checkbox"
                  checked={rows.length > 0 && rows.every((r) => selected?.has(r.id))}
                  onChange={(e) => onSelect(e.target.checked ? new Set(rows.map((r) => r.id)) : new Set())}
                />
              ),
              cell: ({ row }: any) => (
                <input
                  type="checkbox"
                  aria-label={'Select ' + row.original.virtual_path}
                  checked={selected?.has(row.original.id) ?? false}
                  onChange={() => toggle(row.original.id)}
                />
              ),
            },
            ...columns,
          ]
        : columns,
    [columns, selected, onSelect, rows],
  );
  function toggle(id: string) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onSelect?.(next);
  }
  const table = useReactTable({
    data: rows,
    columns: definitions,
    getRowId: (r) => r.id,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    state: { sorting },
    onSortingChange: setSorting,
    columnResizeMode: 'onChange',
    defaultColumn: { minSize: 60, size: 160 },
  });
  const data = table.getRowModel().rows;
  const virtual = useVirtualizer({
    count: data.length,
    getScrollElement: () => viewport.current,
    estimateSize: () => rowHeight,
    overscan: 12,
  });
  useEffect(() => {
    virtual.measure();
  }, [rowHeight]);
  return (
    <div
      ref={viewport}
      className="data-viewport"
      role="region"
      aria-label="Results table"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.target !== e.currentTarget || !data.length) return;
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
          e.preventDefault();
          const next = Math.max(0, Math.min(data.length - 1, focus + (e.key === 'ArrowDown' ? 1 : -1)));
          setFocus(next);
          virtual.scrollToIndex(next);
        }
        if (e.key === ' ' && onSelect) {
          e.preventDefault();
          toggle(data[Math.min(focus, data.length - 1)].id);
        }
      }}
    >
      <table style={{ width: table.getTotalSize() }} aria-rowcount={rows.length + 1}>
        <thead>
          {table.getHeaderGroups().map((group) => (
            <tr key={group.id}>
              {group.headers.map((header) => (
                <th key={header.id} style={{ width: header.getSize() }}>
                  {header.column.getCanSort() ? (
                    <button onClick={header.column.getToggleSortingHandler()}>
                      {flexRender(header.column.columnDef.header, header.getContext())}{' '}
                      {header.column.getIsSorted() === 'asc'
                        ? '↑'
                        : header.column.getIsSorted() === 'desc'
                          ? '↓'
                          : ''}
                    </button>
                  ) : (
                    <span className="column-label">
                      {flexRender(header.column.columnDef.header, header.getContext())}
                    </span>
                  )}
                  {header.column.getCanResize() && (
                    <span
                      className="resizer"
                      onMouseDown={header.getResizeHandler()}
                      onTouchStart={header.getResizeHandler()}
                    />
                  )}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody style={{ height: virtual.getTotalSize(), position: 'relative' }}>
          {virtual.getVirtualItems().map((item) => {
            const row = data[item.index];
            return (
              <tr
                key={row.id}
                aria-rowindex={item.index + 2}
                aria-selected={selected?.has(row.id)}
                className={item.index === focus ? 'focused-row' : ''}
                style={{
                  position: 'absolute',
                  transform: `translateY(${item.start}px)`,
                  height: rowHeight,
                  display: 'flex',
                }}
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} style={{ width: cell.column.getSize(), height: rowHeight }}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
      {!rows.length && <div className="empty">No results to show.</div>}
    </div>
  );
}
