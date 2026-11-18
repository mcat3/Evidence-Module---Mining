import type { RiskFlag } from "@/lib/api";

const SEVERITY: Record<string, { cls: string; icon: string }> = {
  HIGH: { cls: "critical", icon: "▲" },
  MEDIUM: { cls: "warning", icon: "!" },
  LOW: { cls: "info", icon: "i" },
};

const TITLES: Record<string, string> = {
  PIT_EXPANSION: "Pit expansion",
  VEGETATION_LOSS_NEAR_WATER: "Vegetation loss near water",
  NEW_STOCKPILE_FORMATION: "New stockpile formation",
  VEGETATION_LOSS: "Vegetation loss",
};

export default function RiskAlerts({ flags }: { flags: RiskFlag[] }) {
  if (!flags.length) {
    return (
      <div className="risk-empty">
        <span className="status-icon good" aria-hidden>✓</span> No risk patterns crossed their thresholds.
      </div>
    );
  }
  return (
    <ul className="risk-list">
      {flags.map((f) => {
        const s = SEVERITY[f.severity] ?? SEVERITY.LOW;
        return (
          <li key={f.code} className={`risk ${s.cls}`}>
            <div className="risk-head">
              <span className={`sev-chip ${s.cls}`}>
                <span aria-hidden>{s.icon}</span> {f.severity}
              </span>
              <span className="risk-title">{TITLES[f.code] ?? f.code}</span>
              <span className="risk-value mono">{f.unit === "count" ? f.value : `${f.value} ${f.unit}`}</span>
            </div>
            <p>{f.message}</p>
          </li>
        );
      })}
    </ul>
  );
}
