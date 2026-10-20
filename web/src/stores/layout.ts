import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface Layout {
  tabs: { path: string; label: string }[];
  theme: 'dark' | 'light';
  density: 'compact' | 'comfortable';
  open: (path: string, label: string) => void;
  close: (path: string) => void;
  toggleTheme: () => void;
  toggleDensity: () => void;
}
export const useLayout = create<Layout>()(
  persist(
    (set) => ({
      tabs: [],
      theme: 'dark',
      density: 'compact',
      open: (path, label) =>
        set((s) => ({ tabs: [...s.tabs.filter((t) => t.path !== path), { path, label }].slice(-20) })),
      close: (path) => set((s) => ({ tabs: s.tabs.filter((t) => t.path !== path) })),
      toggleTheme: () => set((s) => ({ theme: s.theme === 'dark' ? 'light' : 'dark' })),
      toggleDensity: () => set((s) => ({ density: s.density === 'compact' ? 'comfortable' : 'compact' })),
    }),
    { name: 'nicotine-layout' },
  ),
);
