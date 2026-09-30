import type { ApciCategory, Frame } from '@/lib/types';
import { Badge } from './ui/badge';
import { StatusBadge } from './app-shell';
import { formatTime } from '@/lib/utils';

const CATEGORY_COLORS: Record<ApciCategory, string> = {
  runtime: 'bg-emerald-100 text-emerald-800 border-emerald-300 dark:bg-emerald-950 dark:text-emerald-200',
  programming: 'bg-amber-100 text-amber-800 border-amber-300 dark:bg-amber-950 dark:text-amber-200',
  device: 'bg-blue-100 text-blue-800 border-blue-300 dark:bg-blue-950 dark:text-blue-200',
  memory: 'bg-purple-100 text-purple-800 border-purple-300 dark:bg-purple-950 dark:text-purple-200',
  authorization: 'bg-red-100 text-red-800 border-red-300 dark:bg-red-950 dark:text-red-200',
  property: 'bg-cyan-100 text-cyan-800 border-cyan-300 dark:bg-cyan-950 dark:text-cyan-200',
  diagnostic: 'bg-slate-100 text-slate-700 border-slate-300 dark:bg-slate-800 dark:text-slate-200',
  coupler: 'bg-indigo-100 text-indigo-800 border-indigo-300 dark:bg-indigo-950 dark:text-indigo-200',
  other: 'bg-neutral-100 text-neutral-700 border-neutral-300 dark:bg-neutral-800 dark:text-neutral-200',
  unknown: 'bg-neutral-50 text-neutral-500 border-neutral-200 dark:bg-neutral-900 dark:text-neutral-400',
};

export function CategoryBadge({ category }: { category: ApciCategory | '' }) {
  if (!category) return null;
  const className = CATEGORY_COLORS[category as ApciCategory] || CATEGORY_COLORS.unknown;
  return (
    <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-[10px] font-medium ${className}`}>
      {category}
    </span>
  );
}

export function FramesTable({ frames }: { frames: Frame[] }) {
  if (!frames.length) {
    return (
      <div className="rounded-md border border-dashed border-[color:var(--color-border)] p-8 text-center text-sm text-[color:var(--color-muted-foreground)]">
        Aucune trame collectée pour l'instant. Activez la capture (dumpcap) ou attendez que le collecteur KNX reçoive quelque chose.
      </div>
    );
  }
  return (
    <div className="overflow-x-auto rounded-md border border-[color:var(--color-border)]">
      <table className="w-full text-sm">
        <thead className="bg-[color:var(--color-muted)] text-left text-xs uppercase tracking-wide text-[color:var(--color-muted-foreground)]">
          <tr>
            <th className="px-4 py-2">Heure UTC</th>
            <th className="px-4 py-2">Protocole</th>
            <th className="px-4 py-2">Cat.</th>
            <th className="px-4 py-2">TPCI</th>
            <th className="px-4 py-2">Source</th>
            <th className="px-4 py-2">Destination</th>
            <th className="px-4 py-2">Opération</th>
            <th className="px-4 py-2">Valeur</th>
            <th className="px-4 py-2">DPT</th>
            <th className="px-4 py-2">État</th>
          </tr>
        </thead>
        <tbody>
          {frames.map((f, i) => (
            <tr key={`${f.ts}-${i}`} className="border-t border-[color:var(--color-border)]">
              <td className="px-4 py-2 font-mono text-xs text-[color:var(--color-muted-foreground)]">{formatTime(f.ts)}</td>
              <td className="px-4 py-2">
                <Badge variant="outline">{f.protocol}</Badge>
              </td>
              <td className="px-4 py-2">
                <CategoryBadge category={f.apci_category} />
              </td>
              <td className="px-4 py-2 font-mono text-[10px] text-[color:var(--color-muted-foreground)]">
                {f.tpci || '—'}
              </td>
              <td className="px-4 py-2 font-mono text-xs">{f.src}</td>
              <td className="px-4 py-2 font-mono text-xs">{f.dst}</td>
              <td className="px-4 py-2">{f.operation}</td>
              <td className="px-4 py-2 font-medium">
                {f.value}
                {f.unit && <span className="ml-1 text-xs text-[color:var(--color-muted-foreground)]">{f.unit}</span>}
              </td>
              <td className="px-4 py-2 font-mono text-[10px] text-[color:var(--color-muted-foreground)]">
                {f.dpt || '—'}
              </td>
              <td className="px-4 py-2">
                <StatusBadge value={f.status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
