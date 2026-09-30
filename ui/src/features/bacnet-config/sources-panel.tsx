import { useQuery } from '@tanstack/react-query';
import { InfoField, StatusBadge } from '@/components/app-shell';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { api } from '@/lib/api';
import type { ProtocolSource } from '@/lib/types';

export function SourcesPanel() {
  const sources = useQuery({
    queryKey: ['sources', 'bacnet'],
    queryFn: () => api.sources('bacnet'),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Sources BACnet</CardTitle>
        <CardDescription>
          Écoute passive par défaut — polling actif ou Who-Is à la demande
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid gap-4 xl:grid-cols-2">
          {(sources.data ?? []).map((s) => (
            <SourceCard key={s.id} source={s} />
          ))}
          {sources.data?.length === 0 && (
            <div className="col-span-full py-6 text-center text-sm text-[color:var(--color-muted-foreground)]">
              Aucune source BACnet configurée.
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function SourceCard({ source: s }: { source: ProtocolSource }) {
  const modeLabel =
    s.mode === 'passive' ? 'Écoute passive' : s.mode === 'discovery' ? 'Découverte Who-Is' : 'Polling actif';
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between space-y-0">
        <div>
          <CardTitle className="text-base">{s.name}</CardTitle>
          <p className="mt-1 text-xs text-[color:var(--color-muted-foreground)]">{s.site}</p>
        </div>
        <StatusBadge value={s.status} />
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-4">
        <InfoField label="Mode" value={modeLabel} />
        <InfoField label="Accès" value={`${s.host || 'toute interface'}:${s.port}`} mono />
        <InfoField label="Réseau BACnet" value={String(s.config?.network ?? '—')} />
        <InfoField label="Collecte" value={s.enabled ? 'Activée' : 'Désactivée'} />
      </CardContent>
    </Card>
  );
}
