import { Link, useRouterState } from '@tanstack/react-router';
import { useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  LayoutDashboard,
  Radiation,
  ServerCog,
  Settings,
} from 'lucide-react';
import { cn } from '@/lib/utils';

type SubItem = { label: string; tab: string };
type Section = {
  label: string;
  path: string;
  icon: typeof LayoutDashboard;
  items: SubItem[];
};

const sections: Section[] = [
  {
    label: 'KNX',
    path: '/knx-monitor',
    icon: Radiation,
    items: [
      { label: 'Configuration', tab: 'config' },
      { label: 'Sémantique', tab: 'semantics' },
      { label: 'Trames', tab: 'frames' },
      { label: 'Historique', tab: 'history' },
    ],
  },
  {
    label: 'BACnet',
    path: '/bacnet-monitor',
    icon: Radiation,
    items: [
      { label: 'Configuration', tab: 'config' },
      { label: 'Trames', tab: 'frames' },
      { label: 'Historique', tab: 'history' },
      { label: 'Vue objets & topologie', tab: 'objects' },
    ],
  },
];

export function Sidebar() {
  const { location } = useRouterState();
  const currentPath = location.pathname;
  const currentSearch = location.search as { tab?: string };
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({
    '/knx-monitor': currentPath.startsWith('/knx-monitor'),
    '/bacnet-monitor': currentPath.startsWith('/bacnet-monitor'),
  });

  const toggleSection = (path: string) =>
    setOpenSections(prev => ({ ...prev, [path]: !prev[path] }));

  return (
    <aside className="hidden w-60 shrink-0 border-r border-[color:var(--color-border)] bg-[color:var(--color-sidebar)] md:block">
      <div className="flex h-16 items-center gap-3 border-b border-[color:var(--color-border)] px-4">
        <div className="grid size-8 place-items-center rounded-md bg-[color:var(--color-primary)] text-[color:var(--color-primary-foreground)]">
          <ServerCog className="size-4" />
        </div>
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold">BMS Flight Recorder</div>
          <div className="text-[10px] uppercase tracking-wider text-[color:var(--color-muted-foreground)]">
            v2 · monitoring
          </div>
        </div>
      </div>
      <nav className="flex flex-col gap-1 p-3">
        <Link
          to="/"
          className={cn(
            'flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors',
            currentPath === '/'
              ? 'bg-[color:var(--color-primary)] text-[color:var(--color-primary-foreground)]'
              : 'text-[color:var(--color-sidebar-foreground)] hover:bg-[color:var(--color-muted)]',
          )}
        >
          <LayoutDashboard className="size-4" />
          Vue d'ensemble
        </Link>

        {sections.map(({ label, path, icon: Icon, items }) => {
          const isOpen = openSections[path];
          const isActiveSection = currentPath.startsWith(path);
          return (
            <div key={path} className="flex flex-col">
              <button
                type="button"
                onClick={() => toggleSection(path)}
                className={cn(
                  'flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors',
                  isActiveSection && !currentSearch.tab
                    ? 'bg-[color:var(--color-primary)] text-[color:var(--color-primary-foreground)]'
                    : 'text-[color:var(--color-sidebar-foreground)] hover:bg-[color:var(--color-muted)]',
                )}
              >
                <Icon className="size-4" />
                <span className="flex-1 text-left">{label}</span>
                {isOpen ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
              </button>
              {isOpen && (
                <div className="ml-6 mt-1 flex flex-col gap-0.5 border-l border-[color:var(--color-border)] pl-2">
                  {items.map(({ label: subLabel, tab }) => {
                    const active = isActiveSection && currentSearch.tab === tab;
                    return (
                      <Link
                        key={tab}
                        to={path}
                        search={{ tab }}
                        className={cn(
                          'rounded-md px-3 py-1.5 text-xs transition-colors',
                          active
                            ? 'bg-[color:var(--color-primary)]/15 font-medium text-[color:var(--color-primary)]'
                            : 'text-[color:var(--color-muted-foreground)] hover:bg-[color:var(--color-muted)] hover:text-[color:var(--color-sidebar-foreground)]',
                        )}
                      >
                        {subLabel}
                      </Link>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}

        <Link
          to="/configuration"
          className={cn(
            'mt-2 flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors',
            currentPath === '/configuration'
              ? 'bg-[color:var(--color-primary)] text-[color:var(--color-primary-foreground)]'
              : 'text-[color:var(--color-sidebar-foreground)] hover:bg-[color:var(--color-muted)]',
          )}
        >
          <Settings className="size-4" />
          Configuration
        </Link>
      </nav>
    </aside>
  );
}
