import { useEffect, useRef, useState } from 'react';
import type { BacnetFrame } from '@/lib/types';

export type StreamStatus = 'connecting' | 'open' | 'closed' | 'error';

interface UseBacnetStreamOptions {
  bufferSize?: number;
  filter?: (frame: BacnetFrame) => boolean;
  enabled?: boolean;
}

/**
 * Ouvre une connexion Server-Sent Events vers /api/bacnet/stream et maintient
 * un buffer FIFO des dernières frames BACnet reçues.
 */
export function useBacnetStream({
  bufferSize = 500,
  filter,
  enabled = true,
}: UseBacnetStreamOptions = {}) {
  const [frames, setFrames] = useState<BacnetFrame[]>([]);
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
    const source = new EventSource('/api/bacnet/stream');
    sourceRef.current = source;

    source.onopen = () => setStatus('open');
    source.onerror = () => setStatus('error');
    source.onmessage = (event) => {
      if (!event.data) return;
      try {
        const parsed = JSON.parse(event.data) as BacnetFrame;
        if (filterRef.current && !filterRef.current(parsed)) return;
        setFrames((prev) => {
          const next = [parsed, ...prev];
          if (next.length > bufferSize) next.length = bufferSize;
          return next;
        });
      } catch {
        /* malformed — silently ignore */
      }
    };

    return () => {
      source.close();
      sourceRef.current = null;
      setStatus('closed');
    };
  }, [enabled, bufferSize]);

  const clear = () => setFrames([]);
  return { frames, status, clear };
}
