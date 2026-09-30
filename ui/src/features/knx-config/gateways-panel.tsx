import { Link } from '@tanstack/react-router';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { Plus, Radar, RefreshCw, Trash2, Wifi } from 'lucide-react';
import { toast } from 'sonner';
import { InfoField, StatusBadge } from '@/components/app-shell';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/primitives';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { api } from '@/lib/api';
import { formatDateTime } from '@/lib/utils';
import type { Gateway, ScanJob, DiscoveredDevice, GatewayMode } from '@/lib/types';

const statusVariant: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  queued: 'outline',
  running: 'default',
  completed: 'secondary',
  failed: 'destructive',
};

function parseMetadata(meta: DiscoveredDevice['metadata']): Record<string, string> {
  if (!meta) return {};
  if (typeof meta === 'string') {
    try {
      return JSON.parse(meta);
    } catch {
      return {};
    }
  }
  return meta as Record<string, string>;
}

function gatewayAddress(g: Gateway): string {
  if (g.mode === 'routing') {
    return `${g.multicast_group || '224.0.23.12'}:${g.port}`;
  }
  return `${g.host || '—'}:${g.port}`;
}

export function GatewaysPanel() {
  const queryClient = useQueryClient();

  const gateways = useQuery({
    queryKey: ['gateways'],
    queryFn: api.gateways,
    refetchInterval: 8000,
  });

  const scans = useQuery({
    queryKey: ['scans-knx'],
    queryFn: async () => {
      const all = await api.scans();
      return all.filter((s) => s.protocol === 'knx');
    },
    refetchInterval: (query) => {
      const rows = (query.state.data ?? []) as ScanJob[];
      return rows.some((s) => s.status === 'running' || s.status === 'queued') ? 1500 : 5000;
    },
  });

  const activeScan = scans.data?.[0];
  const discovered = useQuery({
    queryKey: ['scan-devices', activeScan?.id],
    queryFn: () => activeScan ? api.scanDevices(activeScan.id) : Promise.resolve([]),
    enabled: !!activeScan,
    refetchInterval: 2000,
  });

  const startSearch = useMutation({
    mutationFn: () => api.createScan({
      protocol: 'knx',
      mode: 'knx_search',
      target: '224.0.23.12',
      port: 3671,
    }),
    onSuccess: (job) => {
      toast.success(`Recherche KNX lancée (job ${job.id.slice(0, 8)})`);
      queryClient.invalidateQueries({ queryKey: ['scans-knx'] });
    },
    onError: (err: Error) => toast.error(`Erreur : ${err.message}`),
  });

  const deleteGateway = useMutation({
    mutationFn: (id: string) => api.deleteGateway(id),
    onSuccess: () => {
      toast.success('Gateway supprimée');
      queryClient.invalidateQueries({ queryKey: ['gateways'] });
    },
    onError: (err: Error) => toast.error(`Erreur : ${err.message}`),
  });

  return (
    <div className="flex flex-col gap-4">
      {/* Card 1 : Recherche réseau */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <div className="grid size-10 place-items-center rounded-md bg-[#0ea5e9]/10 text-[#0ea5e9]">
              <Radar className="size-5" />
            </div>
            <div className="flex-1">
              <CardTitle>Recherche de gateways KNX/IP</CardTitle>
              <CardDescription>
                Envoie un SEARCH_REQUEST multicast sur 224.0.23.12:3671 — collecte les SEARCH_RESPONSE renvoyés
              </CardDescription>
            </div>
            <Button
              onClick={() => startSearch.mutate()}
              disabled={startSearch.isPending}
            >
              <Wifi className="mr-2 size-4" />
              {startSearch.isPending ? 'Envoi…' : 'Scanner le réseau'}
            </Button>
          </div>
        </CardHeader>

        {activeScan && (
          <CardContent className="border-t border-[color:var(--color-border)] pt-4">
            <div className="mb-3 flex items-center justify-between text-xs">
              <span className="text-[color:var(--color-muted-foreground)]">
                Dernier scan : {formatDateTime(activeScan.created_at)}
              </span>
              <Badge variant={statusVariant[activeScan.status] || 'outline'}>
                {activeScan.status}
              </Badge>
            </div>
            {(discovered.data ?? []).length === 0 ? (
              <div className="py-4 text-center text-sm text-[color:var(--color-muted-foreground)]">
                {activeScan.status === 'running' || activeScan.status === 'queued'
                  ? 'Recherche en cours…'
                  : 'Aucune gateway trouvée pour ce scan.'}
              </div>
            ) : (
              <div className="flex flex-col gap-2">
                {(discovered.data ?? []).map((d) => (
                  <DiscoveredRow key={d.id} device={d} scanId={activeScan.id} />
                ))}
              </div>
            )}
          </CardContent>
        )}
      </Card>

      {/* Card 2 : Gateways configurées */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle>Gateways configurées</CardTitle>
            <CardDescription>
              Interfaces KNX/IP actives (tunneling ou routing multicast)
            </CardDescription>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => gateways.refetch()}
            disabled={gateways.isFetching}
          >
            <RefreshCw className={`size-4 ${gateways.isFetching ? 'animate-spin' : ''}`} />
          </Button>
        </CardHeader>
        <CardContent>
          {(gateways.data ?? []).length === 0 ? (
            <div className="py-8 text-center text-sm text-[color:var(--color-muted-foreground)]">
              Aucune gateway configurée. Lance un scan pour en découvrir sur le réseau.
            </div>
          ) : (
            <div className="grid gap-3 md:grid-cols-2">
              {(gateways.data ?? []).map((g: Gateway) => (
                <GatewayCard key={g.id} gateway={g} onDelete={() => deleteGateway.mutate(g.id)} />
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function GatewayCard({ gateway: g, onDelete }: { gateway: Gateway; onDelete: () => void }) {
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between space-y-0 pb-3">
        <div>
          <CardTitle className="text-base">{g.name}</CardTitle>
          <p className="mt-1 text-xs text-[color:var(--color-muted-foreground)]">
            {g.site || '—'}{g.line ? ` · ligne ${g.line}` : ''}
          </p>
        </div>
        <StatusBadge value={g.status} />
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-3 pt-0">
        <InfoField label="Mode" value={g.mode === 'routing' ? 'Routing multicast' : 'Tunneling'} />
        <InfoField label="Adresse" value={gatewayAddress(g)} mono />
        <InfoField label="Sécurité" value={g.secure ? 'KNX Secure' : 'Non sécurisé'} />
        <InfoField label="Collecte" value={g.enabled ? 'Activée' : 'Désactivée'} />
        <div className="col-span-2 flex justify-end pt-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              if (confirm(`Supprimer la gateway "${g.name}" ?`)) onDelete();
            }}
          >
            <Trash2 className="mr-1 size-3.5" />
            Supprimer
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function DiscoveredRow({ device, scanId }: { device: DiscoveredDevice; scanId: string }) {
  const meta = useMemo(() => parseMetadata(device.metadata), [device.metadata]);
  return (
    <div className="flex items-center justify-between rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-muted)]/30 px-3 py-2 text-sm">
      <div className="flex-1 min-w-0">
        <div className="font-medium truncate">{device.name || 'Gateway KNX/IP'}</div>
        <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-[color:var(--color-muted-foreground)]">
          <span className="font-mono">{device.address}</span>
          {meta.individual_address && (
            <span>individual: <span className="font-mono">{meta.individual_address}</span></span>
          )}
          {meta.knx_medium && <span>medium: {meta.knx_medium}</span>}
          {meta.mac && <span className="font-mono">MAC: {meta.mac}</span>}
        </div>
      </div>
      {device.promoted_gateway_id ? (
        <Badge variant="secondary">Déjà ajoutée</Badge>
      ) : (
        <PromoteDialog scanId={scanId} device={device} defaultName={device.name || 'Gateway KNX'} />
      )}
    </div>
  );
}

function PromoteDialog({
  scanId, device, defaultName,
}: { scanId: string; device: DiscoveredDevice; defaultName: string }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(defaultName);
  const [site, setSite] = useState('');
  const [mode, setMode] = useState<GatewayMode>('routing');

  const promote = useMutation({
    mutationFn: () => api.promoteDevice(scanId, device.id, { name, site, mode }),
    onSuccess: () => {
      toast.success(`Gateway "${name}" ajoutée à la configuration`);
      queryClient.invalidateQueries({ queryKey: ['gateways'] });
      queryClient.invalidateQueries({ queryKey: ['scan-devices', scanId] });
      setOpen(false);
    },
    onError: (err: Error) => toast.error(`Erreur : ${err.message}`),
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <Plus className="mr-1 size-3.5" />
        Ajouter
      </Button>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Ajouter à la configuration</DialogTitle>
          <DialogDescription>
            Promouvoir <span className="font-mono">{device.address}</span> en gateway active.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div>
            <Label htmlFor="promote-name">Nom</Label>
            <Input id="promote-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <Label htmlFor="promote-site">Site / Bâtiment</Label>
            <Input
              id="promote-site" value={site}
              onChange={(e) => setSite(e.target.value)}
              placeholder="ex : Villa Torno"
            />
          </div>
          <div>
            <Label htmlFor="promote-mode">Mode</Label>
            <select
              id="promote-mode"
              className="mt-1 w-full rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-background)] px-3 py-2 text-sm"
              value={mode}
              onChange={(e) => setMode(e.target.value as GatewayMode)}
            >
              <option value="routing">Routing multicast (passif, plusieurs sniffers)</option>
              <option value="tunneling">Tunneling (unicast, 1 client à la fois)</option>
            </select>
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>Annuler</Button>
          <Button onClick={() => promote.mutate()} disabled={promote.isPending}>
            {promote.isPending ? 'Ajout…' : 'Ajouter'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
