// The sidebar's resizable width: pure helpers so the drag, keyboard step and persisted value (kept
// per browser, read and written in try/catch by the caller) all agree on the same bounds and default.
export const MIN = 200;
export const MAX = 480;
export const DEFAULT = 260;
export const STEP = 16;

/** Clamped to [MIN, MAX]. */
export function clampWidth(n: number): number {
  return Math.min(MAX, Math.max(MIN, n));
}

/** The width `localStorage` held, or DEFAULT if it is missing or not a finite number. */
export function parseWidth(stored: string | null): number {
  if (stored === null || stored.trim() === "") return DEFAULT;
  const n = Number(stored);
  return Number.isFinite(n) ? clampWidth(n) : DEFAULT;
}

/** One keyboard step (STEP px) from `current`, clamped. `direction` is -1 (Left, narrower) or 1
 *  (Right, wider). */
export function stepWidth(current: number, direction: -1 | 1): number {
  return clampWidth(current + direction * STEP);
}
