import type { Polygon } from "geojson";

const MINUS = "−";

export function signed(value: number, digits = 1): string {
  const s = Math.abs(value).toFixed(digits);
  if (Number(s) === 0) return s;
  return value < 0 ? `${MINUS}${s}` : `+${s}`;
}

export function fixed(value: number, digits = 1): string {
  return value.toFixed(digits);
}

export function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
}

export const shortHash = (h: string, n = 12) => `${h.slice(0, n)}…${h.slice(-6)}`;

export function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export function shiftYears(iso: string, years: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCFullYear(d.getUTCFullYear() + years);
  return isoDate(d);
}

/** Geodesic area of a lon/lat polygon in km² (spherical excess on the WGS84 mean radius). */
export function polygonAreaKm2(poly: Polygon): number {
  const R = 6371008.8;
  const rad = Math.PI / 180;
  let total = 0;
  poly.coordinates.forEach((ring, i) => {
    let sum = 0;
    for (let k = 0; k < ring.length - 1; k++) {
      const [lon1, lat1] = ring[k];
      const [lon2, lat2] = ring[k + 1];
      sum += (lon2 - lon1) * rad * (2 + Math.sin(lat1 * rad) + Math.sin(lat2 * rad));
    }
    const area = Math.abs((sum * R * R) / 2);
    total += i === 0 ? area : -area;
  });
  return total / 1e6;
}
