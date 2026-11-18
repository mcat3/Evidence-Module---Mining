"""Multi-page PDF Evidence Dossier rendered with ReportLab."""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

INK = colors.HexColor("#1d2733")
MUTED = colors.HexColor("#5b6675")
RULE = colors.HexColor("#d5dae1")
HEAD_BG = colors.HexColor("#eef1f5")
GRADE_COLORS = {"HIGH": colors.HexColor("#1f8a4c"), "MEDIUM": colors.HexColor("#c27c0e"), "LOW": colors.HexColor("#b3261e")}
SEVERITY_COLORS = {"HIGH": colors.HexColor("#b3261e"), "MEDIUM": colors.HexColor("#c27c0e"), "LOW": colors.HexColor("#5b6675")}

PAGE_W, PAGE_H = A4
MARGIN = 16 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

_styles = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=_styles["Heading1"], fontName="Helvetica-Bold", fontSize=19, leading=23, textColor=INK, spaceAfter=2)
H2 = ParagraphStyle("H2", parent=_styles["Heading2"], fontName="Helvetica-Bold", fontSize=12.5, leading=16, textColor=INK,
                    spaceBefore=10, spaceAfter=5)
BODY = ParagraphStyle("Body", parent=_styles["BodyText"], fontName="Helvetica", fontSize=9, leading=12.5, textColor=INK)
SMALL = ParagraphStyle("Small", parent=BODY, fontSize=7.5, leading=10, textColor=MUTED)
CELL = ParagraphStyle("Cell", parent=BODY, fontSize=8, leading=10)
CAPTION = ParagraphStyle("Caption", parent=SMALL, alignment=TA_CENTER)
MONO = ParagraphStyle("Mono", parent=CELL, fontName="Courier", fontSize=7, leading=9)


def _fmt(v, digits=1, signed=False, unit=""):
    if v is None:
        return "n/a"
    s = f"{v:+,.{digits}f}" if signed else f"{v:,.{digits}f}"
    return f"{s}{unit}"


def _table(rows, col_widths, *, header=True, zebra=True, align_right_from=1):
    t = Table(rows, colWidths=col_widths, repeatRows=1 if header else 0)
    style = [("FONT", (0, 0), (-1, -1), "Helvetica", 8), ("TEXTCOLOR", (0, 0), (-1, -1), INK),
             ("LINEBELOW", (0, 0), (-1, -1), 0.25, RULE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if align_right_from is not None:
        style.append(("ALIGN", (align_right_from, 0), (-1, -1), "RIGHT"))
    if header:
        style += [("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8), ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG)]
    if zebra:
        for r in range(2 if header else 1, len(rows), 2):
            style.append(("BACKGROUND", (0, r), (-1, r), colors.HexColor("#f8f9fb")))
    t.setStyle(TableStyle(style))
    return t


class _ImageCache:
    def __init__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="terraproof_pdf_"))

    def flatten(self, path: Path, max_px: int = 900) -> str:
        """Composite transparent PNGs onto white and downscale so the PDF stays small."""
        out = self.dir / f"{path.stem}.jpg"
        with PILImage.open(path) as im:
            im = im.convert("RGBA")
            bg = PILImage.new("RGBA", im.size, (255, 255, 255, 255))
            bg.alpha_composite(im)
            rgb = bg.convert("RGB")
            rgb.thumbnail((max_px, max_px))
            rgb.save(out, "JPEG", quality=88)
        return str(out)

    def image(self, path: Path, width: float) -> Image:
        src = self.flatten(path)
        with PILImage.open(src) as im:
            w, h = im.size
        return Image(src, width=width, height=width * h / w)


def _footer(site: str, package_hash: str):
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, PAGE_H - 11 * mm, PAGE_W - MARGIN, PAGE_H - 11 * mm)
        canvas.setFont("Helvetica-Bold", 7.5)
        canvas.setFillColor(INK)
        canvas.drawString(MARGIN, PAGE_H - 9.5 * mm, "TerraProof  |  Mining Activity Evidence Dossier")
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 9.5 * mm, site)
        canvas.line(MARGIN, 14 * mm, PAGE_W - MARGIN, 14 * mm)
        canvas.setFont("Courier", 6.5)
        canvas.drawString(MARGIN, 10 * mm, f"Evidence package SHA-256: {package_hash}")
        canvas.setFont("Helvetica", 7)
        canvas.drawRightString(PAGE_W - MARGIN, 10 * mm, f"Page {doc.page}")
        canvas.drawString(MARGIN, 6.5 * mm, "Verify: recompute SHA-256 over evidence_package.json (excluding 'integrity') "
                                            "using the stated canonicalization.")
        canvas.restoreState()
    return draw


def _executive_summary(pkg: dict) -> str:
    k = pkg["outputs"]["kpis"]
    scenes = pkg["inputs"]["satellite_scenes"]
    base = scenes.get("baseline", {}).get("acquired", "")[:10]
    tgt = scenes.get("target", {}).get("acquired", "")[:10]
    parts = [f"Sentinel-2 L2A imagery of <b>{pkg['site_name']}</b> ({pkg['inputs']['aoi_area_ha']:,.0f} ha AOI) "
             f"acquired on <b>{base or 'n/a'}</b> (baseline) and <b>{tgt}</b> (target) was classified into five "
             "mining land-cover classes and compared pixel-by-pixel."]
    if "pit_expansion_ha" in k:
        pit = k["pit_expansion_ha"]
        pit_text = (f"active pit / exposed coal area decreased by {abs(pit):,.1f} ha ({k['pit_expansion_pct']:+.1f}%), "
                    "consistent with backfilling or coal-face migration" if pit < 0 else
                    f"active pit area expanded by {pit:,.1f} ha ({k['pit_expansion_pct']:+.1f}%)")
        parts.append(f"Between the two dates the {pit_text}; overburden / stockpile area changed by "
                     f"{k['overburden_change_ha']:+,.1f} ha, and {k['vegetation_lost_to_mining_ha']:,.1f} ha of previously "
                     f"undisturbed land was converted to pit or overburden. {k['new_stockpiles_detected']} new stockpile "
                     "bodies were detected.")
    parts.append(f"The classifier's mean confidence on the target date is {k['mean_confidence_pct']:.1f}% and the overall "
                 f"Evidence Reliability Grade is <b>{k['evidence_reliability_grade']}</b>.")
    return " ".join(parts)


def build_pdf_report(pkg: dict, artifact_dir: str | Path, out_path: str | Path) -> str:
    artifact_dir, out_path = Path(artifact_dir), Path(out_path)
    out = pkg["outputs"]
    k, integrity = out["kpis"], pkg["integrity"]
    cache = _ImageCache()
    story = []

    grade = k["evidence_reliability_grade"]
    story += [Paragraph("Mining Activity Evidence Dossier", H1),
              Paragraph(f"{pkg['site_name']}  |  generated {pkg['packaged_at'][:19].replace('T', ' ')} UTC", SMALL),
              Spacer(1, 6)]

    badge = Table([[Paragraph(f"<font color='white'><b>EVIDENCE RELIABILITY: {grade}</b></font>", BODY)]],
                  colWidths=[CONTENT_W])
    badge.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), GRADE_COLORS.get(grade, MUTED)),
                               ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story += [badge, Spacer(1, 8)]

    story += [Paragraph("Executive Summary", H2), Paragraph(_executive_summary(pkg), BODY), Spacer(1, 6)]

    kpi_cells = [("Pit area change", _fmt(k.get("pit_expansion_ha"), signed=True, unit=" ha")),
                 ("Overburden change", _fmt(k.get("overburden_change_ha"), signed=True, unit=" ha")),
                 ("Vegetation lost to mining", _fmt(k.get("vegetation_lost_to_mining_ha"), unit=" ha")),
                 ("New stockpiles", str(k.get("new_stockpiles_detected", "n/a"))),
                 ("Mean confidence", f"{k['mean_confidence_pct']:.1f}%"),
                 ("Risk flags", str(k.get("risk_flag_count", 0)))]
    kpi_rows = []
    for i in range(0, len(kpi_cells), 3):
        kpi_rows.append([Paragraph(f"<font size=7 color='#5b6675'>{label.upper()}</font><br/>"
                                   f"<font size=13><b>{value}</b></font>", BODY) for label, value in kpi_cells[i:i + 3]])
    kpi_table = Table(kpi_rows, colWidths=[CONTENT_W / 3] * 3)
    kpi_table.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, RULE), ("INNERGRID", (0, 0), (-1, -1), 0.5, RULE),
                                   ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
    story += [kpi_table]

    story.append(Paragraph("Risk Alerts", H2))
    if out["risk_flags"]:
        rows = [["Severity", "Code", "Finding"]]
        for f in out["risk_flags"]:
            sev = f["severity"]
            rows.append([Paragraph(f"<font color='#{SEVERITY_COLORS[sev].hexval()[2:]}'><b>{sev}</b></font>", CELL),
                         Paragraph(f["code"], CELL), Paragraph(f["message"], CELL)])
        story.append(_table(rows, [18 * mm, 58 * mm, CONTENT_W - 76 * mm], align_right_from=None))
    else:
        story.append(Paragraph("No risk patterns exceeded their thresholds.", BODY))

    story.append(Paragraph("Satellite Scene Provenance", H2))
    rows = [["Role", "Scene ID", "Acquired (UTC)", "Scene cloud", "AOI cloud", "Sun elev."]]
    for role, s in pkg["inputs"]["satellite_scenes"].items():
        rows.append([role.title(), Paragraph(s["scene_id"], MONO), s["acquired"][:19].replace("T", " "),
                     _fmt(s.get("scene_cloud_pct"), 2, unit="%"), _fmt(s.get("aoi_cloud_pct"), 2, unit="%"),
                     _fmt(s.get("sun_elevation_deg"), 1, unit=" deg")])
    story.append(_table(rows, [17 * mm, 55 * mm, 33 * mm, 22 * mm, 20 * mm, CONTENT_W - 147 * mm], align_right_from=3))
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"Source: {', '.join(sorted({s['stac_api'] for s in pkg['inputs']['satellite_scenes'].values()}))} "
                           f"(Sentinel-2 L2A). Grid: {pkg['inputs']['processing_grid']['crs']}, "
                           f"{pkg['inputs']['processing_grid']['resolution_m']:.0f} m.", SMALL))

    story.append(PageBreak())
    story.append(Paragraph("Before / After Comparison", H2))
    half = (CONTENT_W - 6 * mm) / 2
    has_base = (artifact_dir / "baseline_rgb.png").exists()
    pairs = [("rgb", "True colour (B04-B03-B02)"), ("landcover", "ML land-cover classification")]
    for key, label in pairs:
        cells, caps = [], []
        for role in (("baseline", "target") if has_base else ("target",)):
            cells.append(cache.image(artifact_dir / f"{role}_{key}.png", half))
            date = pkg["inputs"]["satellite_scenes"][role]["acquired"][:10]
            caps.append(Paragraph(f"{label} - {role} ({date})", CAPTION))
        t = Table([cells, caps], colWidths=[half + 3 * mm] * len(cells))
        t.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story += [t, Spacer(1, 4)]
    legend = [[Paragraph(f"<font color='#{''.join(f'{c:02x}' for c in v['rgb'])}'>&#9632;</font> {v['name']}", SMALL)
               for v in out["class_legend"].values()]]
    story.append(Table(legend, colWidths=[CONTENT_W / 5] * 5))

    if out["change_detection"]:
        story.append(PageBreak())
        cd = out["change_detection"]
        story.append(Paragraph("Hectare Change by Class", H2))
        rows = [["Class", "Baseline (ha)", "Target (ha)", "Change (ha)", "Change (%)"]]
        for name, v in cd["per_class"].items():
            rows.append([name, _fmt(v["baseline_ha"]), _fmt(v["target_ha"]), _fmt(v["change_ha"], signed=True),
                         _fmt(v["change_pct"], signed=True, unit="%")])
        story.append(_table(rows, [68 * mm, 27 * mm, 27 * mm, 27 * mm, CONTENT_W - 149 * mm]))
        story.append(Paragraph(f"Compared only where both dates are cloud-free: {cd['comparable_area_ha']:,.1f} ha.", SMALL))

        story.append(Paragraph("Land-Cover Transition Matrix (ha)", H2))
        abbrev = ["Veg.", "Pit", "Overburden", "Water", "Roads/Built"]
        rows = [["Baseline \\ Target"] + abbrev]
        for name, vals in zip(abbrev, cd["transition_matrix_ha"]["values"]):
            rows.append([name] + [_fmt(x) for x in vals])
        story.append(_table(rows, [34 * mm] + [(CONTENT_W - 34 * mm) / 5] * 5))

        stockpiles = out["geojson_layers"].get("new_stockpiles", {}).get("features", [])
        if stockpiles:
            story.append(Paragraph("New Stockpile Bodies (largest 12)", H2))
            rows = [["ID", "Area (ha)", "Dominant material (SAM)", "Purity", "Centroid (lat, lon)"]]
            for f in sorted(stockpiles, key=lambda f: -f["properties"]["area_ha"])[:12]:
                p = f["properties"]
                ring = f["geometry"]["coordinates"][0]
                lat = sum(c[1] for c in ring) / len(ring)
                lon = sum(c[0] for c in ring) / len(ring)
                rows.append([str(p.get("stockpile_id")), _fmt(p["area_ha"], 2), p.get("dominant_mineral", "n/a"),
                             _fmt(p.get("mineral_purity_pct"), unit="%"), f"{lat:.5f}, {lon:.5f}"])
            story.append(_table(rows, [14 * mm, 20 * mm, 58 * mm, 18 * mm, CONTENT_W - 110 * mm]))

    story.append(PageBreak())
    hs = out["hyperspectral_mineral_tags"]
    story.append(Paragraph("Hyperspectral Mineral Tagging (Spectral Angle Mapper)", H2))
    if (artifact_dir / "hyperspectral_signatures.png").exists():
        story.append(cache.image(artifact_dir / "hyperspectral_signatures.png", CONTENT_W * 0.82))
    rows = [["Material", "Area (ha)", "Share of tagged"]]
    for name, v in hs["composition"].items():
        rows.append([name, _fmt(v["area_ha"]), _fmt(v["pct_of_tagged"], unit="%")])
    story.append(_table(rows, [80 * mm, 40 * mm, CONTENT_W - 120 * mm]))
    story.append(Paragraph(f"<b>Data source:</b> {hs['data_source']}. Pixels analysed: {hs['pixels_analysed']:,}; "
                           f"tagged: {hs['tagged_pct']:.1f}%; angle threshold {hs['angle_threshold_rad']} rad.", SMALL))

    va = out["validation_audit"]
    story.append(Paragraph("Validation & Uncertainty Audit", H2))
    rows = [["Check", "Baseline", "Target"]]
    per = va["per_date"]
    for label, key, unit in (("Cloud-free AOI", "cloud_free_aoi_pct", "%"), ("Mean confidence", "mean_confidence", ""),
                             ("Median confidence", "median_confidence", ""),
                             ("Pixels below 70% confidence", "low_confidence_pct", "%")):
        rows.append([label] + [_fmt(per[r][key], 3 if unit == "" else 2, unit=unit) if r in per else "n/a"
                               for r in ("baseline", "target")])
    co = va["qa_checks"].get("coregistration")
    if co:
        rows.append(["Co-registration offset", f"{co['shift_px']:.3f} px ({co['shift_m']:.2f} m)",
                     "PASS" if co["pass"] else "FAIL"])
    story.append(_table(rows, [70 * mm, 55 * mm, CONTENT_W - 125 * mm]))
    story.append(Paragraph(f"Grade <b>{va['evidence_reliability_grade']}</b>: {'; '.join(va['grade_reasons'])}.", BODY))

    m = out["model"]
    story.append(Paragraph("Methodology & Limitations", H2))
    story.append(Paragraph(
        f"Land cover: {m['model']} ({m['params']['n_estimators']} trees) on {len(m['features'])} spectral and spatial-context "
        f"features, {m['training_strategy']}. Agreement with held-out pseudo-labels: "
        f"{100 * m['pseudo_label_holdout_agreement']:.1f}% - this measures consistency with the bootstrap rules, not "
        "accuracy against field ground truth. Dry-season fallow and agricultural land is reported within "
        "'Undisturbed Vegetation' (non-mining land). Mineral tags derive from a simulated hyperspectral cube and are "
        "indicative only. Independent accuracy can be scored against surveyed polygons with "
        "scripts/score_ground_truth.py.", BODY))

    story.append(KeepTogether([
        Paragraph("Cryptographic Provenance", H2),
        _table([["Hash", "SHA-256"],
                ["Evidence package", Paragraph(integrity["package_sha256"], MONO)],
                ["Input satellite metadata", Paragraph(integrity["input_metadata_sha256"], MONO)],
                ["Output spatial metrics", Paragraph(integrity["output_metrics_sha256"], MONO)],
                ["Artifact manifest", Paragraph(integrity["artifact_manifest_sha256"], MONO)]],
               [45 * mm, CONTENT_W - 45 * mm], align_right_from=None),
        Paragraph(f"Canonicalization: {integrity['canonicalization']}. {len(pkg['artifact_manifest'])} artifact files are "
                  "individually hashed in the package's artifact_manifest.", SMALL),
    ]))

    doc = SimpleDocTemplate(str(out_path), pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                            topMargin=16 * mm, bottomMargin=20 * mm, title=f"TerraProof Evidence Dossier - {pkg['site_name']}",
                            author="TerraProof", subject=f"SHA-256 {integrity['package_sha256']}",
                            creator="TerraProof evidence builder")
    footer = _footer(pkg["site_name"], integrity["package_sha256"])
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return str(out_path)


def build_evidence(summary: dict, artifact_dir: str | Path, *, job_id: str | None = None,
                   artifact_names=None) -> dict:
    """Write evidence_package.json and evidence_report.pdf; return hashes and paths."""
    from .evidence_builder import (PACKAGE_NAME, PUBLISHED_ARTIFACTS, REPORT_NAME, build_evidence_package,
                                   sha256_file)

    artifact_dir = Path(artifact_dir)
    package = build_evidence_package(summary, artifact_dir, job_id=job_id,
                                     artifact_names=artifact_names or PUBLISHED_ARTIFACTS)
    pdf_path = Path(build_pdf_report(package, artifact_dir, artifact_dir / REPORT_NAME))
    return {
        "package_path": str(artifact_dir / PACKAGE_NAME),
        "report_path": str(pdf_path),
        "package_sha256": package["integrity"]["package_sha256"],
        "package_file_sha256": sha256_file(artifact_dir / PACKAGE_NAME),
        "report_sha256": sha256_file(pdf_path),
        "built_at": datetime.now(timezone.utc).isoformat(),
    }
