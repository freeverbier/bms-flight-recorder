import { useMemo, useState } from 'react';
import { LineChart as LineChartIcon, Pause, Play, Trash2 } from 'lucide-react';
import type { BacnetFrame } from '@/lib/types';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { StatusBadge } from '@/components/app-shell';
import { cn, formatTime } from '@/lib/utils';
import { useBacnetStream, type StreamStatus } from './use-bacnet-stream';

const statusLabel: Record<StreamStatus, string> = {
  connecting: 'Connexion…',
  open: 'En ligne',
  closed: 'Fermé',
  error: 'Erreur / reconnexion',
};

const serviceTone: Record<string, string> = {
  iAm: 'bg-emerald-100 text-emerald-800 border-emerald-200',
  whoIs: 'bg-slate-100 text-slate-800 border-slate-200',
  readProperty: 'bg-blue-100 text-blue-800 border-blue-200',
  readPropertyMultiple: 'bg-blue-100 text-blue-800 border-blue-200',
  writeProperty: 'bg-amber-100 text-amber-800 border-amber-200',
  writePropertyMultiple: 'bg-amber-100 text-amber-800 border-amber-200',
  confirmedCOVNotification: 'bg-violet-100 text-violet-800 border-violet-200',
  unconfirmedCOVNotification: 'bg-violet-100 text-violet-800 border-violet-200',
  subscribeCOV: 'bg-teal-100 text-teal-800 border-teal-200',
};

const apduTone: Record<string, string> = {
  'Error': 'bg-red-100 text-red-800 border-red-200',
  'Reject': 'bg-red-100 text-red-800 border-red-200',
  'Abort': 'bg-red-100 text-red-800 border-red-200',
};

interface Props {
  onShowHistory?: (addressAndField: string) => void;
}

export function FrameList({ onShowHistory }: Props) {
  const [paused, setPaused] = useState(false);
  const [query, setQuery] = useState('');

  const { frames, status, clear } = useBacnetStream({
    enabled: !paused,
    bufferSize: 1000,
  });

  const filtered = useMemo(() => {
    if (!query.trim()) return frames;
    const q = query.trim().toLowerCase();
    return frames.filter((f) =>
      [f.src, f.dst, f.service, f.object_ref, f.property, f.value, f.point_name, f.operation_detail].some((v) =>
        (v || '').toLowerCase().includes(q),
      ),
    );
  }, [frames, query]);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filtrer par service, IP, object-ref, property, valeur…"
          className="max-w-sm"
        />
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

      <div className="max-h-[600px] overflow-y-auto overflow-x-auto rounded-md border border-[color:var(--color-border)]">
        <table className="w-full text-sm">
          <thead className="sticky top-0 z-10 bg-[color:var(--color-muted)] text-left text-xs uppercase tracking-wide text-[color:var(--color-muted-foreground)]">
            <tr>
              <th className="px-3 py-2">Horodatage</th>
              <th className="px-3 py-2">Source</th>
              <th className="px-3 py-2">Object</th>
              <th className="px-3 py-2">Service</th>
              <th className="px-3 py-2">Property</th>
              <th className="px-3 py-2">Valeur</th>
              <th className="px-3 py-2 w-10"></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((f, idx) => {
              const key = `${f.ts}-${idx}`;
              const svcTone = serviceTone[f.service || ''] || 'bg-slate-100 text-slate-700 border-slate-200';
              const apduToneCls = apduTone[f.apdu_type || ''];
              const isHistorable = !!(f.object_ref && f.value_num !== null && f.value_num !== undefined);
              return (
                <tr key={key} className="border-t border-[color:var(--color-border)] hover:bg-[color:var(--color-muted)]/30">
                  <td className="px-3 py-2 font-mono text-xs whitespace-nowrap">{formatTime(f.ts)}</td>
                  <td className="px-3 py-2 font-mono text-xs">{f.src}</td>
                  <td className="px-3 py-2 font-mono text-xs">
                    {f.object_ref || '—'}
                    {f.point_name && (
                      <div className="text-[10px] text-[color:var(--color-muted-foreground)]">{f.point_name}</div>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <Badge className={cn('text-[10px]', svcTone)}>
                      {f.service || f.apdu_type || f.bvlc_function}
                    </Badge>
                    {apduToneCls && (
                      <Badge className={cn('ml-1 text-[10px]', apduToneCls)}>{f.apdu_type}</Badge>
                    )}
                  </td>
                  <td className="px-3 py-2 text-xs">{f.property || '—'}</td>
                  <td className="px-3 py-2 text-xs font-mono">
                    {f.value !== '' && f.value !== null && f.value !== undefined
                      ? `${f.value}${f.unit ? ' ' + f.unit : ''}`
                      : '—'}
                  </td>
                  <td className="px-3 py-2">
                    {isHistorable && onShowHistory && (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="size-6 p-0"
                        title="Voir l'historique"
                        onClick={() => onShowHistory(`${f.object_ref}|value_num`)}
                      >
                        <LineChartIcon className="size-3" />
                      </Button>
                    )}
                  </td>
                </tr>
              );
            })}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-sm text-[color:var(--color-muted-foreground)]">
                  {paused
                    ? 'Stream suspendu. Reprends pour recevoir les frames.'
                    : 'En attente de trafic BACnet… ou aucun filtre ne matche.'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="text-xs text-[color:var(--color-muted-foreground)]">
        {filtered.length} / {frames.length} frame(s) affichée(s)
      </div>
    </div>
  );
}
