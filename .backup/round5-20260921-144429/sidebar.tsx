import { Link, useRouterState } from '@tanstack/react-router';
import {
  Activity,
  CircleGauge,
  FileKey2,
  LayoutDashboard,
  Radar,
  Radio,
  Radiation,
  ServerCog,
  Settings,
  Waypoints,
} from 'lucide-react';
import { cn } from '@/lib/utils';

const nav = [
  { to: '/', label: "Vue d'ensemble", icon: LayoutDashboard },
  { to: '/scan', label: 'Scan réseau', icon: Radar },
  { to: '/knx-monitor', label: 'Monitoring KNX', icon: Radiation },
  { to: '/frames', label: 'Trames', icon: Activity },
  { to: '/values', label: 'Valeurs', icon: CircleGauge },
  { to: '/sources', label: 'Sources', icon: Radio },
  { to: '/gateways', label: 'Gateways KNX', icon: Waypoints },
  { to: '/credentials', label: 'Identifiants', icon: FileKey2 },
  { to: '/configuration', label: 'Configuration', icon: Settings },
] as const;

export function Sidebar() {
  const { location } = useRouterState();
  const currentPath = location.pathname;

  return (
    <aside className="hidden w-56 shrink-0 border-r border-[color:var(--color-border)] bg-[color:var(--color-sidebar)] md:block">
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
        {nav.map(({ to, label, icon: Icon }) => {
          const active = to === '/' ? currentPath === to : currentPath.startsWith(to);
          return (
            <Link
              key={to}
              to={to}
              className={cn(
                'flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors',
                active
                  ? 'bg-[color:var(--color-primary)] text-[color:var(--color-primary-foreground)]'
                  : 'text-[color:var(--color-sidebar-foreground)] hover:bg-[color:var(--color-muted)]',
              )}
            >
              <Icon className="size-4" />
              {label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
