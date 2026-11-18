import type { JobResult } from "@/lib/api";
import { fixed, signed } from "@/lib/format";

const GRADE_STATUS: Record<string, { cls: string; icon: string }> = {
  HIGH: { cls: "good", icon: "✓" },
  MEDIUM: { cls: "warning", icon: "!" },
  LOW: { cls: "critical", icon: "✕" },
};

function Tile({ label, value, unit, note, className = "" }: {
  label: string; value: React.ReactNode; unit?: string; note: React.ReactNode; className?: string;
}) {
  return (
    <div className={`kpi ${className}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">
        {value}
        {unit && <span className="kpi-unit">{unit}</span>}
      </div>
      <div className="kpi-note">{note}</div>
    </div>
  );
}

export default function KpiGrid({ result }: { result: JobResult }) {
  const k = result.kpis;
  const grade = GRADE_STATUS[k.evidence_reliability_grade] ?? GRADE_STATUS.LOW;
  const stockpileHa = result.risk_metrics?.new_stockpile_ha;
  const pitPct = k.pit_expansion_pct;
  return (
    <div className="kpi-grid">
      <Tile label="Pit area change" value={signed(k.pit_expansion_ha)} unit="ha"
        note={pitPct == null ? "no baseline pit" : `${signed(pitPct)}% vs baseline${k.pit_expansion_ha < 0 ? " · net backfill" : ""}`} />
      <Tile label="Overburden change" value={signed(k.overburden_change_ha)} unit="ha"
        note="Dumps & mineral stockpiles" />
      <Tile label="Vegetation lost to mining" value={fixed(k.vegetation_lost_to_mining_ha)} unit="ha"
        note={`Net vegetation ${signed(k.vegetation_change_ha)} ha`} />
      <Tile label="New stockpiles" value={k.new_stockpiles_detected}
        note={stockpileHa != null ? `≥ 1 ha each · ${fixed(stockpileHa)} ha total` : "≥ 1 ha each"} />
      <Tile label="Model confidence" value={fixed(k.mean_confidence_pct)} unit="%"
        note={`Mean pixel certainty · ${fixed(result.validation.per_date.target?.low_confidence_pct ?? 0)}% of pixels below 70%`} />
      <Tile label="Evidence reliability" className={`kpi-grade ${grade.cls}`}
        value={<><span className={`status-icon ${grade.cls}`} aria-hidden>{grade.icon}</span>{k.evidence_reliability_grade}</>}
        note={result.validation.reasons.join("; ")} />
    </div>
  );
}
