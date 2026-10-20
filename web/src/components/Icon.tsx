const paths: Record<string, string> = {
  search: 'M21 21l-6-6 M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0',
  downloads: 'M12 3v12 m-5-5 5 5 5-5 M4 16v5h16v-5',
  uploads: 'M12 15V3 m-5 5 5-5 5 5 M4 16v5h16v-5',
  rooms: 'M3 4h18v12H9l-6 5V4 M7 8h10 M7 12h7',
  private: 'M3 5h18v14H3V5 m0 1 9 7 9-7',
  buddies:
    'M16 21v-3a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v3 M10 10a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M17 3a4 4 0 0 1 0 8 M20 21v-3a4 4 0 0 0-3-4',
  browse: 'M3 6h7l2 3h9v12H3V6 M3 6V3h7l2 3h7v3',
  interests: 'M12 3 3 12l9 9 9-9-9-9 M12 8v8 M8 12h8',
  shares: 'M3 6h7l2 3h9v12H3V6 M12 12v6 M9 15h6',
  plugins: 'M8 3v5 M16 3v5 M6 8h12v5a6 6 0 0 1-12 0V8 M12 19v3',
  stats: 'M3 3v18h18 M7 17v-5 M12 17V7 M17 17v-8',
  settings: 'M4 6h16 M4 12h16 M4 18h16 M8 3v6 M16 9v6 M10 15v6',
  notifications: 'M5 17h14l-2-4V9a5 5 0 0 0-10 0v4l-2 4 M10 21h4',
};

export function Icon({ name }: { name: string }) {
  return (
    <svg
      className="app-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name] ?? paths.search} />
    </svg>
  );
}
