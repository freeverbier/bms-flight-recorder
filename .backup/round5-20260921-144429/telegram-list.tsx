import { useMemo, useState } from 'react';
import { Link } from '@tanstack/react-router';
import { useQuery } from '@tanstack/react-query';
import { ArrowRight, Pause, Play, Radar, Trash2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { StatusBadge } from '@/components/app-shell';
import { api } from '@/lib/api';
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

export function TelegramList() {
  const [paused, setPaused] = useState(false);
  const [query, setQuery] = useState('');

  const gateways = useQuery({
    queryKey: ['gateways'],
    queryFn: api.gateways,
    refetchInterval: 15_000,
  });

  const { telegrams, status, clear } = useKnxStream({
    enabled: !paused,
    bufferSize: 1000,
  });

  const filtered = useMemo(() => {
    if (!query.trim()) return telegrams;
    const q = query.trim().toLowerCase();
    return telegrams.filter((t) =>
      [t.source, t.destination, t.apci, t.value, t.point_name, t.dpt].some((v) =>
        (v || '').toLowerCase().includes(q),
      ),
    );
  }, [telegrams, query]);

  const gws = gateways.data ?? [];
  const hasGateway = gws.length > 0;
  const hasOnlineGateway = gws.some((g) => g.enabled && g.status === 'online');

  if (!gateways.isLoading && !hasGateway) {
    return (
      <div className="py-12 text-center">
        <div className="mx-auto mb-4 grid size-12 place-items-center rounded-full bg-[color:var(--color-muted)]">
          <Radar className="size-6 text-[color:var(--color-primary)]" />
        </div>
        <h2 className="mb-2 text-lg font-semibold">Aucune gateway KNX configurée</h2>
        <p className="mx-auto mb-6 max-w-md text-sm text-[color:var(--color-muted-foreground)]">
          Lance un scan pour découvrir tes équipements KNX et les ajouter au monitoring en un clic.
        </p>
        <Button asChild>
          <Link to="/scan">
            Aller au scan réseau
            <ArrowRight />
          </Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filtrer par adresse, groupe, DPT ou nom…"
          className="max-w-sm"
        />
        <div className="ml-auto flex items-center gap-2">
          <StatusBadge
            value={status === 'open' ? 'online' : status === 'error' ? 'degraded' : 'configured'}
          />
          <span className="text-xs text-[color:var(--color-muted-foreground)]">
            {statusLabel[status]}
          </span>
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

      {!hasOnlineGateway && (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          <strong>Aucune gateway en ligne pour l'instant.</strong>{' '}
          Vérifie l'état sur la page{' '}
          <Link to="/gateways" className="underline">
            Gateways KNX
          </Link>
          {' '}— la sonde s'y reconnecte automatiquement toutes les 15 secondes.
        </div>
      )}

      <div className="overflow-x-auto rounded-md border border-[color:var(--color-border)]">
        <table className="w-full text-sm">
          <thead className="bg-[color:var(--color-muted)] text-left text-xs uppercase tracking-wide text-[color:var(--color-muted-foreground)]">
            <tr>
              <th className="px-3 py-2">Horodatage</th>
              <th className="px-3 py-2">Source</th>
              <th className="px-3 py-2">Destination</th>
              <th className="px-3 py-2">APCI</th>
              <th className="px-3 py-2">DPT / Nom</th>
              <th className="px-3 py-2">Valeur</th>
              <th className="px-3 py-2">Priorité</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((t, i) => (
              <tr
                key={`${t.ts}-${t.raw_hex}-${i}`}
                className="animate-flash border-t border-[color:var(--color-border)]"
              >
                <td className="px-3 py-2 font-mono text-xs text-[color:var(--color-muted-foreground)]">
                  {formatTime(t.ts)}
                </td>
                <td className="px-3 py-2 font-mono text-xs">{t.source}</td>
                <td className="px-3 py-2 font-mono text-xs">{t.destination}</td>
                <td className="px-3 py-2">
                  <Badge variant="outline">{t.apci}</Badge>
                </td>
                <td className="px-3 py-2">
                  <div className="text-xs font-medium">
                    {t.point_name || (
                      <span className="text-[color:var(--color-muted-foreground)]">—</span>
                    )}
                  </div>
                  {t.dpt && (
                    <div className="text-xs text-[color:var(--color-muted-foreground)]">
                      DPT {t.dpt}
                    </div>
                  )}
                </td>
                <td className="px-3 py-2 font-medium">
                  {t.value ? (
                    <>
                      {t.value}
                      {t.unit && (
                        <span className="ml-1 text-[color:var(--color-muted-foreground)]">
                          {t.unit}
                        </span>
                      )}
                    </>
                  ) : (
                    <span className="text-xs text-[color:var(--color-muted-foreground)]">
                      brut · {t.raw_hex.slice(0, 24)}…
                    </span>
                  )}
                </td>
                <td className="px-3 py-2">
                  <span
                    className={cn(
                      'rounded border px-2 py-0.5 text-xs font-medium',
                      priorityTone[t.priority] || 'bg-slate-100 text-slate-700',
                    )}
                  >
                    {t.priority || '—'}
                  </span>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td
                  colSpan={7}
                  className="px-4 py-10 text-center text-sm text-[color:var(--color-muted-foreground)]"
                >
                  {paused
                    ? 'Stream suspendu.'
                    : hasOnlineGateway
                      ? "En attente de trafic KNX sur le bus…"
                      : "Le flux est ouvert, mais aucune gateway ne remonte encore de télégrammes."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-[color:var(--color-muted-foreground)]">
        {telegrams.length} télégramme(s) en mémoire · filtrage local. Le buffer garde les 1000
        dernières trames.
      </p>
    </div>
  );
}
