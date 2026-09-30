import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const numberFormat = new Intl.NumberFormat('fr-CH');

export function formatNumber(value: number): string {
  return numberFormat.format(value);
}

export function formatTime(iso: string): string {
  return iso.slice(11, 23);
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return `${d.toLocaleDateString('fr-CH')} ${d.toLocaleTimeString('fr-CH')}`;
}
