// Vue Historique KNX — sélecteur GA, période, field ; graphique SVG.
// Consommé par la nouvelle tab "Historique" dans knx-monitor.tsx.

import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Clock, Radio } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { api } from '@/lib/api';
import type { HistoryRange, KnxHistoryResponse } from '@/lib/types';
import { LineChart } from './line-chart';

const RANGES: { value: HistoryRange; label: string }[] = [
  { value: '1h', label: '1 h' },
  { value: '6h', label: '6 h' },
  { value: '24h', label: '24 h' },
  { value: '7d', label: '7 j' },
  { value: '30d', label: '30 j' },
];

interface HistoryTabProps {
  initialAddress?: string;
  initialField?: string;
  initialRange?: HistoryRange;
  onAddressChange?: (address: string) => void;
  onFieldChange?: (field: string) => void;
  onRangeChange?: (range: HistoryRange) => void;
}

const selectClass =
  'h-9 rounded-md border border-[color:var(--color-input)] bg-transparent px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--color-ring)]';

export function HistoryTab({
  initialAddress = '',
  initialField = 'value_num',
  initialRange = '24h',
  onAddressChange,
  onFieldChange,
  onRangeChange,
}: HistoryTabProps) {
  const [address, setAddress] = useState(initialAddress);
  const [addressInput, setAddressInput] = useState(initialAddress);
  const [field, setField] = useState(initialField);
  const [range, setRange] = useState<HistoryRange>(initialRange);
  const [autoRefresh, setAutoRefresh] = useState(false);

  // Sync avec les props (quand on arrive depuis le bouton du live)
  useMemo(() => {
    if (initialAddress && initialAddress !== address) {
      setAddress(initialAddress);
      setAddressInput(initialAddress);
    }
    if (initialField && initialField !== field) setField(initialField);
    if (initialRange && initialRange !== range) setRange(initialRange);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialAddress, initialField, initialRange]);

  // Autocomplete GA depuis knx_group_addresses
  const groups = useQuery({
    queryKey: ['knx-groups-autocomplete'],
    queryFn: () => api.knxGroupAddresses(),
    staleTime: 60_000,
  });

  const suggestions = useMemo(() => {
    if (!addressInput.trim()) return [];
    const q = addressInput.trim().toLowerCase();
    return (groups.data ?? [])
      .filter((g) =>
        g.address.toLowerCase().includes(q) ||
        (g.name || '').toLowerCase().includes(q),
      )
      .slice(0, 8);
  }, [addressInput, groups.data]);

  const [showSuggestions, setShowSuggestions] = useState(false);

  const history = useQuery<KnxHistoryResponse>({
    queryKey: ['knx-history', address, range, field],
    queryFn: () => api.knxHistory(address, range, field),
    enabled: !!address,
    refetchInterval: autoRefresh ? 15_000 : false,
  });

  const commitAddress = (a: string) => {
    setAddress(a);
    setAddressInput(a);
    setShowSuggestions(false);
    onAddressChange?.(a);
  };

  const commitField = (f: string) => {
    setField(f);
    onFieldChange?.(f);
  };

  const commitRange = (r: HistoryRange) => {
    setRange(r);
    onRangeChange?.(r);
  };

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Historique</CardTitle>
          <CardDescription>
            Trace la valeur d'une adresse de groupe dans le temps.
            Downsampling automatique selon la fenêtre pour rester fluide.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 lg:grid-cols-[2fr_1fr_2fr_auto]">
            {/* Sélecteur GA avec autocomplete */}
            <div className="relative">
              <label className="mb-1 block text-xs font-medium text-[color:var(--color-muted-foreground)]">
                Adresse de groupe
              </label>
              <Input
                value={addressInput}
                onChange={(e) => {
                  setAddressInput(e.target.value);
                  setShowSuggestions(true);
                }}
                onFocus={() => setShowSuggestions(true)}
                onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') commitAddress(addressInput.trim());
                }}
                placeholder="ex. 3/4/5"
                className="font-mono"
              />
              {showSuggestions && suggestions.length > 0 && (
                <div className="absolute z-10 mt-1 w-full rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-popover)] shadow-lg">
                  {suggestions.map((g) => (
                    <button
                      key={g.address}
                      type="button"
                      className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-[color:var(--color-muted)]"
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => commitAddress(g.address)}
                    >
                      <span>
                        <span className="font-mono text-xs">{g.address}</span>
                        {g.name && <span className="ml-2 text-xs text-[color:var(--color-muted-foreground)]">{g.name}</span>}
                      </span>
                      {g.dpt && <Badge variant="outline" className="text-[10px]">{g.dpt}</Badge>}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Sélecteur field */}
            <div>
              <label className="mb-1 block text-xs font-medium text-[color:var(--color-muted-foreground)]">
                Champ
              </label>
              <select
                value={field}
                onChange={(e) => commitField(e.target.value)}
                className={`${selectClass} w-full`}
              >
                <option value="value_num">value_num</option>
                {(history.data?.meta.available_fields ?? [])
                  .filter((f) => f !== 'value_num')
                  .map((f) => (
                    <option key={f} value={f}>{f}</option>
                  ))}
              </select>
            </div>

            {/* Sélecteur période */}
            <div>
              <label className="mb-1 block text-xs font-medium text-[color:var(--color-muted-foreground)]">
                Fenêtre
              </label>
              <div className="flex gap-1">
                {RANGES.map((r) => (
                  <Button
                    key={r.value}
                    size="sm"
                    variant={range === r.value ? 'default' : 'outline'}
                    onClick={() => commitRange(r.value)}
                    className="flex-1"
                  >
                    {r.label}
                  </Button>
                ))}
              </div>
            </div>

            {/* Auto-refresh */}
            <div>
              <label className="mb-1 block text-xs font-medium text-[color:var(--color-muted-foreground)]">
                &nbsp;
              </label>
              <Button
                size="sm"
                variant={autoRefresh ? 'default' : 'outline'}
                onClick={() => setAutoRefresh((v) => !v)}
              >
                <Radio className={autoRefresh ? 'animate-pulse' : ''} />
                {autoRefresh ? 'Live' : 'Statique'}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {!address && (
        <div className="rounded-md border border-dashed border-[color:var(--color-border)] p-10 text-center text-sm text-[color:var(--color-muted-foreground)]">
          Saisis une adresse de groupe ci-dessus, ou clique sur l'icône 📈 dans le flux temps réel.
        </div>
      )}

      {address && history.isLoading && (
        <div className="rounded-md border border-[color:var(--color-border)] p-10 text-center text-sm">
          Chargement…
        </div>
      )}

      {address && history.error && (
        <div className="rounded-md border border-red-300 bg-red-50 p-4 text-sm text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
          Erreur : {(history.error as Error).message}
        </div>
      )}

      {address && history.data && (
        <Card>
          <CardHeader>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <CardTitle className="flex items-center gap-2">
                  <span className="font-mono">{history.data.meta.address}</span>
                  {history.data.meta.point_name && (
                    <span className="text-[color:var(--color-muted-foreground)]">
                      · {history.data.meta.point_name}
                    </span>
                  )}
                </CardTitle>
                <CardDescription className="mt-1 flex flex-wrap items-center gap-2">
                  {history.data.meta.dpt && (
                    <Badge variant="outline" className="text-[10px]">DPT {history.data.meta.dpt}</Badge>
                  )}
                  <span>
                    {history.data.points.length} points ·
                    bucket {formatBucket(history.data.meta.bucket_s)} ·
                    {history.data.meta.total_frames.toLocaleString('fr-CH')} trames sur la fenêtre
                  </span>
                </CardDescription>
              </div>
              <div className="text-right text-xs text-[color:var(--color-muted-foreground)]">
                <div className="flex items-center gap-1 justify-end">
                  <Clock className="size-3" />
                  {formatDate(history.data.meta.from)}
                  &nbsp;→&nbsp;
                  {formatDate(history.data.meta.to)}
                </div>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {history.data.points.length === 0 ? (
              <div className="rounded-md border border-dashed border-[color:var(--color-border)] p-10 text-center text-sm text-[color:var(--color-muted-foreground)]">
                Aucune trame décodée sur cette fenêtre pour ce champ.
                {history.data.meta.total_frames > 0 && (
                  <div className="mt-2">
                    ({history.data.meta.total_frames.toLocaleString('fr-CH')} trames existent mais
                    aucune n'a de valeur numérique pour <span className="font-mono">{history.data.meta.field}</span>.)
                  </div>
                )}
              </div>
            ) : (
              <LineChart
                points={history.data.points}
                unit={history.data.meta.unit}
                height={360}
              />
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function formatBucket(s: number): string {
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.round(s / 60)}min`;
  if (s < 86400) return `${Math.round(s / 3600)}h`;
  return `${Math.round(s / 86400)}j`;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('fr-CH', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}
