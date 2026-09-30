import * as React from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Sidebar } from './sidebar';
import { cn } from '@/lib/utils';

export function AppShell({ children }: { children: React.ReactNode }) {
  const { data: summary } = useQuery({
    queryKey: ['summary'],
    queryFn: api.summary,
    refetchInterval: 15_000,
  });

  return (
    <div className="flex min-h-screen bg-[color:var(--color-background)] text-[color:var(--color-foreground)]">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-[color:var(--color-border)] bg-[color:var(--color-background)]/95 px-6 backdrop-blur">
          <div className="text-sm text-[color:var(--color-muted-foreground)]">
            {summary?.packets_per_second !== undefined ? (
              <span className="inline-flex items-center gap-2">
                <span className="size-2 animate-pulse rounded-full bg-emerald-500" />
                Collecte active — {summary.packets_per_second} trames/s
              </span>
            ) : (
              <span className="inline-flex items-center gap-2 text-[color:var(--color-muted-foreground)]">
                <span className="size-2 rounded-full bg-amber-500" />
                En attente de télémétrie
              </span>
            )}
          </div>
        </header>
        <main className="min-w-0 flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && (
          <p className="mt-1 text-sm text-[color:var(--color-muted-foreground)]">{subtitle}</p>
        )}
      </div>
      {action}
    </div>
  );
}

const STATUS_LABELS: Record<string, string> = {
  online: 'En ligne',
  offline: 'Hors ligne',
  degraded: 'Dégradé',
  configured: 'Configuré',
  queued: 'En attente',
  running: 'En cours',
  completed: 'Terminé',
  failed: 'Échec',
  credential_required: 'Identifiant requis',
  good: 'Valide',
  ok: 'OK',
};

const STATUS_TONES: Record<string, string> = {
  online: 'bg-emerald-500',
  ok: 'bg-emerald-500',
  good: 'bg-emerald-500',
  completed: 'bg-emerald-500',
  configured: 'bg-slate-400',
  queued: 'bg-slate-400',
  running: 'bg-blue-500',
  degraded: 'bg-amber-500',
  offline: 'bg-red-500',
  failed: 'bg-red-500',
  credential_required: 'bg-amber-500',
};

export function StatusBadge({ value }: { value: string }) {
  const label = STATUS_LABELS[value] || value;
  const tone = STATUS_TONES[value] || 'bg-slate-400';
  return (
    <span className="inline-flex items-center gap-2 text-xs font-medium">
      <span className={cn('size-2 rounded-full', tone)} />
      {label}
    </span>
  );
}

export function InfoField({ label, value, mono = false }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <p className="text-xs uppercase tracking-wide text-[color:var(--color-muted-foreground)]">{label}</p>
      <p className={cn('mt-1 truncate text-sm font-medium', mono && 'font-mono text-xs')}>{value}</p>
    </div>
  );
}
