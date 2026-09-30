import type { Frame } from '@/lib/types';
import { Badge } from '@/components/ui/badge';
import { formatDateTime } from '@/lib/utils';

const protocolTone: Record<string, string> = {
  knx: 'bg-cyan-100 text-cyan-800 dark:bg-cyan-950 dark:text-cyan-200',
  bacnet: 'bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-200',
  modbus: 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200',
};

const sourceKindLabel: Record<string, string> = {
  gateway: 'Collecteur',
  pcap: 'Capture PCAP',
  polling: 'Polling',
};

export function FramesTable({ frames }: { frames: Frame[] }) {
  if (!frames.length) {
    return (
      <p className="p-8 text-center text-sm text-[color:var(--color-muted-foreground)]">
        Aucune trame remontée pour l'instant.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-md border border-[color:var(--color-border)]">
      <table className="w-full text-sm">
        <thead className="bg-[color:var(--color-muted)] text-left text-xs uppercase tracking-wide text-[color:var(--color-muted-foreground)]">
          <tr>
            <th className="px-3 py-2">Horodatage</th>
            <th className="px-3 py-2">Protocole</th>
            <th className="px-3 py-2">Origine</th>
            <th className="px-3 py-2">Source</th>
            <th className="px-3 py-2">Destination</th>
            <th className="px-3 py-2">Opération</th>
            <th className="px-3 py-2">Valeur</th>
          </tr>
        </thead>
        <tbody>
          {frames.map((f, i) => (
            <tr
              key={`${f.ts}-${f.source_id}-${i}`}
              className="border-t border-[color:var(--color-border)]"
            >
              <td className="px-3 py-2 font-mono text-xs text-[color:var(--color-muted-foreground)]">
                {formatDateTime(f.ts)}
              </td>
              <td className="px-3 py-2">
                <span
                  className={`rounded px-2 py-0.5 text-xs font-medium ${
                    protocolTone[f.protocol.toLowerCase()] || 'bg-slate-100 text-slate-700'
                  }`}
                >
                  {f.protocol.toUpperCase()}
                </span>
              </td>
              <td className="px-3 py-2 text-xs text-[color:var(--color-muted-foreground)]">
                {sourceKindLabel[f.source_kind] || f.source_kind}
              </td>
              <td className="px-3 py-2 font-mono text-xs">{f.src || '—'}</td>
              <td className="px-3 py-2 font-mono text-xs">{f.dst || '—'}</td>
              <td className="px-3 py-2">
                <div className="text-xs">{f.operation || '—'}</div>
                {f.dpt && (
                  <div className="text-[10px] text-[color:var(--color-muted-foreground)]">
                    DPT {f.dpt}
                  </div>
                )}
              </td>
              <td className="px-3 py-2 font-medium">
                {f.point_name && (
                  <div className="text-xs text-[color:var(--color-muted-foreground)]">
                    {f.point_name}
                  </div>
                )}
                {f.value ? (
                  <>
                    {f.value}
                    {f.unit && (
                      <span className="ml-1 text-xs text-[color:var(--color-muted-foreground)]">
                        {f.unit}
                      </span>
                    )}
                  </>
                ) : (
                  <span className="text-xs text-[color:var(--color-muted-foreground)]">—</span>
                )}
                {f.status !== 'ok' && (
                  <Badge variant="warning" className="ml-2">
                    {f.status}
                  </Badge>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
