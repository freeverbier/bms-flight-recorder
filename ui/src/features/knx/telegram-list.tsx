import { useMemo, useState } from 'react';
import { LineChart as LineChartIcon, Pause, Play, Trash2 } from 'lucide-react';
import type { ApciCategory, KnxTelegram } from '@/lib/types';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { StatusBadge } from '@/components/app-shell';
import { CategoryBadge } from '@/components/frames-table';
import { cn, formatTime } from '@/lib/utils';
import { useKnxStream, type StreamStatus } from './use-knx-stream';

const statusLabel: Record<StreamStatus, string> = {
  connecting: 'Connexion…',
  open: 'En ligne',
  closed: 'Fermé',
  error: 'Erreur / reconnexion',
};

const priorityTone: Record<string, string> = {
  system: 'bg-red-100 text-red-800 border-red-200',
  urgent: 'bg-amber-100 text-amber-800 border-amber-200',
  normal: 'bg-blue-100 text-blue-800 border-blue-200',
  low: 'bg-slate-100 text-slate-800 border-slate-200',
};

const CATEGORY_FILTERS: { value: ApciCategory | ''; label: string }[] = [
  { value: '', label: 'Toutes' },
  { value: 'runtime', label: 'Runtime' },
  { value: 'programming', label: 'Programming' },
  { value: 'device', label: 'Device' },
  { value: 'memory', label: 'Memory' },
  { value: 'property', label: 'Property' },
  { value: 'authorization', label: 'Authorization' },
  { value: 'diagnostic', label: 'Diagnostic' },
  { value: 'coupler', label: 'Coupler' },
];

const selectClass =
  'h-9 rounded-md border border-[color:var(--color-input)] bg-transparent px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--color-ring)]';

interface TelegramListProps {
  /** Round 6 : callback pour ouvrir l'historique de cette GA (bouton 📈 par ligne) */
  onShowHistory?: (address: string) => void;
}

export function TelegramList({ onShowHistory }: TelegramListProps = {}) {
  const [paused, setPaused] = useState(false);
  const [query, setQuery] = useState('');
  const [categoryFilter, setCategoryFilter] = useState<ApciCategory | ''>('');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const { telegrams, status, clear } = useKnxStream({
    enabled: !paused,
    bufferSize: 1000,
  });

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return telegrams.filter((t: KnxTelegram) => {
      if (categoryFilter && t.apci_category !== categoryFilter) return false;
      if (!q) return true;
      return [t.source, t.destination, t.apci, t.value, t.point_name, t.dpt].some((v) =>
        (v || '').toLowerCase().includes(q),
      );
    });
  }, [telegrams, query, categoryFilter]);

  const toggleExpanded = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const isGroupAddress = (a: string) => a.includes('/');

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filtrer par adresse, groupe, DPT ou nom…"
          className="max-w-sm"
        />
        <select
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value as ApciCategory | '')}
          className={selectClass}
        >
          {CATEGORY_FILTERS.map((f) => (
            <option key={f.value || 'all'} value={f.value}>{f.label}</option>
          ))}
        </select>
        <div className="ml-auto flex items-center gap-2">
          <StatusBadge value={status === 'open' ? 'online' : status === 'error' ? 'degraded' : 'configured'} />
          <span className="text-xs text-[color:var(--color-muted-foreground)]">{statusLabel[status]}</span>
          <Button variant="outline" size="sm" onClick={() => setPaused((p) => !p)}>
            {paused ? <Play /> : <Pause />}
            {paused ? 'Reprendre' : 'Suspendre'}
          </Button>
          <Button variant="ghost" size="sm" onClick={clear}>
            <Trash2 />
            Vider
          </Button>
        </div>
      </div>

      <div className="overflow-x-auto rounded-md border border-[color:var(--color-border)]">
        <table className="w-full text-sm">
          <thead className="bg-[color:var(--color-muted)] text-left text-xs uppercase tracking-wide text-[color:var(--color-muted-foreground)]">
            <tr>
              <th className="px-3 py-2">Horodatage</th>
              <th className="px-3 py-2">Cat.</th>
              <th className="px-3 py-2">Source</th>
              <th className="px-3 py-2">Destination</th>
              <th className="px-3 py-2">APCI / TPCI</th>
              <th className="px-3 py-2">DPT / Nom</th>
              <th className="px-3 py-2">Valeur</th>
              <th className="px-3 py-2">Priorité</th>
              <th className="px-3 py-2 w-8"></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((t: KnxTelegram, i: number) => {
              const key = `${t.ts}-${t.raw_hex}-${i}`;
              const isExpanded = expanded.has(key);
              const hasExtra = t.extra && Object.keys(t.extra).length > 0;
              const canGraph = onShowHistory && isGroupAddress(t.destination);
              return (
                <>
                  <tr
                    key={key}
                    className={cn(
                      'animate-flash border-t border-[color:var(--color-border)] cursor-pointer hover:bg-[color:var(--color-muted)]',
                      isExpanded && 'bg-[color:var(--color-muted)]',
                    )}
                    onClick={() => hasExtra && toggleExpanded(key)}
                  >
                    <td className="px-3 py-2 font-mono text-xs text-[color:var(--color-muted-foreground)]">
                      {formatTime(t.ts)}
                    </td>
                    <td className="px-3 py-2">
                      <CategoryBadge category={t.apci_category} />
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">{t.source}</td>
                    <td className="px-3 py-2 font-mono text-xs">{t.destination}</td>
                    <td className="px-3 py-2">
                      <Badge variant="outline">{t.apci}</Badge>
                      {t.tpci && (
                        <div className="mt-1 font-mono text-[10px] text-[color:var(--color-muted-foreground)]">
                          {t.tpci}
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <div className="text-xs font-medium">
                        {t.point_name || <span className="text-[color:var(--color-muted-foreground)]">—</span>}
                      </div>
                      {t.dpt && (
                        <div className="text-xs text-[color:var(--color-muted-foreground)]">DPT {t.dpt}</div>
                      )}
                    </td>
                    <td className="px-3 py-2 font-medium">
                      {t.value ? (
                        <>
                          {t.value}
                          {t.unit && <span className="ml-1 text-[color:var(--color-muted-foreground)]">{t.unit}</span>}
                        </>
                      ) : (
                        <span className="text-xs text-[color:var(--color-muted-foreground)]">brut · {t.raw_hex.slice(0, 24)}…</span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <span className={cn('rounded border px-2 py-0.5 text-xs font-medium', priorityTone[t.priority] || 'bg-slate-100 text-slate-700')}>
                        {t.priority || '—'}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      {canGraph && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="size-7 p-0"
                          title={`Historique de ${t.destination}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            onShowHistory?.(t.destination);
                          }}
                        >
                          <LineChartIcon className="size-3.5" />
                        </Button>
                      )}
                    </td>
                  </tr>
                  {isExpanded && hasExtra && (
                    <tr className="border-t border-[color:var(--color-border)] bg-[color:var(--color-muted)]/40">
                      <td colSpan={9} className="px-4 py-3">
                        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
                          {Object.entries(t.extra).map(([k, v]) => (
                            <div key={k} className="flex items-start gap-2">
                              <div className="flex-1">
                                <div className="text-[10px] uppercase tracking-wide text-[color:var(--color-muted-foreground)]">{k}</div>
                                <div className="font-mono text-xs break-all">{v}</div>
                              </div>
                              {canGraph && (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="size-6 p-0 shrink-0"
                                  title={`Tracer ${k} pour ${t.destination}`}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    onShowHistory?.(t.destination + '|extra.' + k);
                                  }}
                                >
                                  <LineChartIcon className="size-3" />
                                </Button>
                              )}
                            </div>
                          ))}
                        </div>
                        <div className="mt-2 text-[10px] text-[color:var(--color-muted-foreground)]">
                          Raw : <span className="font-mono">{t.raw_hex}</span>
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              );
            })}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={9} className="px-4 py-10 text-center text-sm text-[color:var(--color-muted-foreground)]">
                  {paused
                    ? 'Stream suspendu.'
                    : status === 'open'
                      ? 'En attente de télégrammes… (vérifie qu\'au moins une gateway KNX est configurée)'
                      : 'Connexion au flux temps réel en cours…'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-[color:var(--color-muted-foreground)]">
        {telegrams.length} télégramme(s) en mémoire · filtrage local. Le buffer garde les 1000 dernières trames.
        Clic sur une ligne : détails N2. Icône <LineChartIcon className="inline size-3" /> : ouvrir l'historique
        de la GA (ou du champ extra).
      </p>
    </div>
  );
}
