import { useEffect, useRef, useState } from 'react';
import type { KnxTelegram } from '@/lib/types';

export type StreamStatus = 'connecting' | 'open' | 'closed' | 'error';

interface UseKnxStreamOptions {
  /** Nombre maximal de télégrammes conservés en mémoire (par défaut 500). */
  bufferSize?: number;
  /** Filtre optionnel — retourne true pour conserver la trame. */
  filter?: (telegram: KnxTelegram) => boolean;
  /** Désactive le stream (utile pour l'arrêter proprement lors du démontage). */
  enabled?: boolean;
}

/**
 * Ouvre une connexion Server-Sent Events vers /api/knx/stream et maintient
 * un buffer FIFO des derniers télégrammes reçus.
 *
 * Reconnexion automatique gérée par le navigateur (EventSource) ; on
 * remonte les changements d'état pour l'affichage.
 */
export function useKnxStream({
  bufferSize = 500,
  filter,
  enabled = true,
}: UseKnxStreamOptions = {}) {
  const [telegrams, setTelegrams] = useState<KnxTelegram[]>([]);
  const [status, setStatus] = useState<StreamStatus>('connecting');
  const sourceRef = useRef<EventSource | null>(null);
  const filterRef = useRef(filter);
  filterRef.current = filter;

  useEffect(() => {
    if (!enabled) {
      setStatus('closed');
      return;
    }
    setStatus('connecting');
    const source = new EventSource('/api/knx/stream');
    sourceRef.current = source;

    source.onopen = () => setStatus('open');
    source.onerror = () => setStatus('error');
    source.onmessage = (event) => {
      if (!event.data) return;
      try {
        const parsed = JSON.parse(event.data) as KnxTelegram;
        if (filterRef.current && !filterRef.current(parsed)) return;
        setTelegrams((prev) => {
          const next = [parsed, ...prev];
          if (next.length > bufferSize) next.length = bufferSize;
          return next;
        });
      } catch {
        /* payload malformé — on l'ignore silencieusement, un log serveur suffit */
      }
    };

    return () => {
      source.close();
      sourceRef.current = null;
      setStatus('closed');
    };
  }, [bufferSize, enabled]);

  const clear = () => setTelegrams([]);

  return { telegrams, status, clear };
}
