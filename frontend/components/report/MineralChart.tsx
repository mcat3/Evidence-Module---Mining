import type { JobResult } from "@/lib/api";
import { fixed } from "@/lib/format";
import { mineralColor } from "@/lib/layers";

/** Horizontal bar chart of SAM mineral composition; every bar is direct-labelled so colour never carries identity alone. */
export default function MineralChart({ hs }: { hs: JobResult["hyperspectral"] }) {
  const rows = Object.entries(hs.composition).sort((a, b) => b[1].pct_of_tagged - a[1].pct_of_tagged);
  const max = Math.max(...rows.map(([, v]) => v.pct_of_tagged), 1);
  return (
    <figure className="mineral-chart">
      <ul>
        {rows.map(([name, v]) => (
          <li key={name} className="bar-row" tabIndex={0}>
            <div className="bar-label">
              <span className="swatch" style={{ background: mineralColor(name) }} aria-hidden />
              <span className="bar-name">{name}</span>
              <span className="bar-value mono">{fixed(v.pct_of_tagged)}%</span>
            </div>
            <div className="bar-track">
              <div className="bar-fill" style={{ width: `${(v.pct_of_tagged / max) * 100}%`, background: mineralColor(name) }} />
            </div>
            <div className="bar-tip" role="tooltip">
              <strong>{name}</strong>
              <span>{fixed(v.area_ha)} ha · {fixed(v.pct_of_tagged)}% of tagged mining surface</span>
            </div>
          </li>
        ))}
      </ul>
      <figcaption>
        {hs.pixels_analysed.toLocaleString()} mining-class pixels analysed · {fixed(hs.tagged_pct)}% matched a reference
        spectrum. <em>Hyperspectral cube is simulated (EnMAP-like, 211 bands) from real Sentinel-2 pixels.</em>
      </figcaption>
    </figure>
  );
}
