import { useQuery } from '@tanstack/react-query';
import { PageHeader, StatusBadge } from '@/components/app-shell';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { api } from '@/lib/api';

export function CredentialsPanel() {
  const credentials = useQuery({ queryKey: ['credentials'], queryFn: api.credentials });

  return (
    <>
      <PageHeader
        title="Identifiants et clés"
        subtitle="Secrets chiffrés côté serveur (Fernet), jamais réaffichés en clair"
      />

      <Card>
        <CardHeader>
          <CardTitle>Profils enregistrés</CardTitle>
          <CardDescription>
            Les imports (keyring KNX, TLS, PKCS#12) se font depuis les pages spécialisées : le keyring KNX via
            la page « Monitoring KNX » → onglet Sémantique.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {(credentials.data ?? []).map((c) => (
              <div key={c.id} className="flex items-center justify-between rounded-md border border-[color:var(--color-border)] p-4">
                <div>
                  <div className="text-sm font-medium">{c.name}</div>
                  <div className="text-xs text-[color:var(--color-muted-foreground)]">
                    <Badge variant="outline" className="mr-2">{c.kind}</Badge>
                    scope: {c.scope}
                    {c.fingerprint && <span className="ml-2 font-mono">empreinte {c.fingerprint}</span>}
                  </div>
                </div>
                <StatusBadge value="good" />
              </div>
            ))}
            {credentials.data?.length === 0 && (
              <p className="p-4 text-center text-sm text-[color:var(--color-muted-foreground)]">
                Aucun identifiant importé.
              </p>
            )}
          </div>
        </CardContent>
      </Card>
    </>
  );
}
