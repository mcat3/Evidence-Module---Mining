import type { JobResult } from "@/lib/api";
import { fixed, signed } from "@/lib/format";

/** Diverging bars (gain right / loss left around a neutral zero line), with the signed hectares as direct labels. */
export default function LandCoverChange({ result }: { result: JobResult }) {
  const rows = Object.entries(result.change_detection.per_class).sort((a, b) => a[1].class_id - b[1].class_id);
  const max = Math.max(...rows.map(([, c]) => Math.abs(c.change_ha)), 1);
  return (
    <table className="lc-table">
      <thead>
        <tr>
          <th scope="col">Class</th>
          <th scope="col" className="num">Baseline</th>
          <th scope="col" className="num">Target</th>
          <th scope="col" className="lc-bar-col">Change (ha)</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([name, c]) => {
          const rgb = result.class_legend[String(c.class_id)]?.rgb ?? [128, 128, 128];
          const w = (Math.abs(c.change_ha) / max) * 50;
          return (
            <tr key={name} title={`${name}: ${fixed(c.baseline_ha)} → ${fixed(c.target_ha)} ha (${signed(c.change_ha)} ha)`}>
              <th scope="row">
                <span className="swatch" style={{ background: `rgb(${rgb.join(",")})` }} aria-hidden />
                {name}
              </th>
              <td className="num mono">{fixed(c.baseline_ha)}</td>
              <td className="num mono">{fixed(c.target_ha)}</td>
              <td className="lc-bar-col">
                <div className="div-bar">
                  <span className="div-zero" />
                  <span className={`div-fill ${c.change_ha < 0 ? "neg" : "pos"}`}
                    style={c.change_ha < 0 ? { right: "50%", width: `${w}%` } : { left: "50%", width: `${w}%` }} />
                </div>
                <span className="mono div-label">{signed(c.change_ha)}</span>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
