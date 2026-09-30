import { createFileRoute } from '@tanstack/react-router';
import { PageHeader } from '@/components/app-shell';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';

export const Route = createFileRoute('/configuration')({
  component: ConfigurationPage,
});

function ConfigurationPage() {
  return (
    <>
      <PageHeader
        title="Configuration"
        subtitle="Paramètres de la sonde, rétention et modes actifs"
      />
      <div className="grid gap-4 xl:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Capture réseau</CardTitle>
            <CardDescription>Interface définie par CAPTURE_INTERFACE (variable .env)</CardDescription>
          </CardHeader>
          <CardContent className="text-sm">
            Filtre BPF appliqué :
            <code className="mt-2 block rounded bg-[color:var(--color-muted)] p-2 text-xs">
              udp port 3671 or tcp port 502 or tcp port 802 or udp portrange 47808-47823
            </code>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Rétention PCAP</CardTitle>
            <CardDescription>Ring buffer dumpcap</CardDescription>
          </CardHeader>
          <CardContent className="text-sm">
            <p>Fichiers de 100 Mo × 96 (paramétrable dans .env).</p>
            <p className="mt-1 text-[color:var(--color-muted-foreground)]">≈ 9,6 Go de trafic conservé.</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Rétention trames</CardTitle>
            <CardDescription>ClickHouse</CardDescription>
          </CardHeader>
          <CardContent className="text-sm">
            180 jours (TTL sur <code>bms.frames</code>).
          </CardContent>
        </Card>
      </div>
    </>
  );
}
