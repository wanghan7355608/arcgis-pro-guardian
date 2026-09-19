"""Core audit and reporting logic for ArcGIS Pro Guardian.

This module deliberately imports no ArcGIS packages at import time. ArcPy is
injected by the CLI, which keeps policy, rendering, diffing, and most audit
logic testable on machines that do not have ArcGIS Pro installed.
"""

from __future__ import annotations

import copy
import hashlib
import html
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional


SCHEMA_VERSION = 2
TOOL_VERSION = "0.2.0"
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
FAIL_ON_CHOICES = ("never", "error", "warning")
RASTER_EXTENSIONS = (".tif", ".tiff", ".img", ".jp2", ".png", ".jpg", ".jpeg")

DEFAULT_POLICY: Dict[str, Any] = {
    "checks": {
        "NO_MAPS": "error",
        "EMPTY_MAP": "warning",
        "BROKEN_LAYER": "error",
        "BROKEN_TABLE": "error",
        "MISSING_DATA_SOURCE": "error",
        "ABSOLUTE_SOURCE_PATH": "warning",
        "UNC_SOURCE_PATH": "warning",
        "SOURCE_OUTSIDE_ALLOWED_ROOTS": "warning",
        "SOURCE_IN_BLOCKED_ROOT": "error",
        "DUPLICATE_LAYER_NAMES": "warning",
        "DUPLICATE_TABLE_NAMES": "warning",
        "UNKNOWN_SPATIAL_REFERENCE": "warning",
        "MIXED_SPATIAL_REFERENCES": "warning",
        "NO_LAYOUTS": "info",
        "LAYOUT_WITHOUT_MAP_FRAME": "warning",
    },
    "score_weights": {"error": 25, "warning": 6, "info": 0},
    "fail_on": "error",
    "require_layout": False,
    "allowed_source_roots": [],
    "blocked_source_roots": [],
}

RECOMMENDATIONS = {
    "NO_MAPS": "Add at least one map or remove the empty project from the delivery package.",
    "EMPTY_MAP": "Populate the map or remove it before handoff.",
    "BROKEN_LAYER": "Repair the layer data source in ArcGIS Pro and save a copy before re-auditing.",
    "BROKEN_TABLE": "Repair the standalone table data source and re-audit the saved project.",
    "MISSING_DATA_SOURCE": "Confirm the source is mounted and accessible, then repair or package it.",
    "ABSOLUTE_SOURCE_PATH": "Package the source with the project or move it under an approved shared root.",
    "UNC_SOURCE_PATH": "Confirm recipients can reach the network share or package the source locally.",
    "SOURCE_OUTSIDE_ALLOWED_ROOTS": "Move or reconnect the source under a policy-approved root.",
    "SOURCE_IN_BLOCKED_ROOT": "Reconnect the source outside the blocked root before release.",
    "DUPLICATE_LAYER_NAMES": "Rename layers so map contents and exported legends are unambiguous.",
    "DUPLICATE_TABLE_NAMES": "Rename standalone tables to make automation and handoff unambiguous.",
    "UNKNOWN_SPATIAL_REFERENCE": "Define or verify the source coordinate system before analysis.",
    "MIXED_SPATIAL_REFERENCES": "Verify on-the-fly projection is intentional and document transformations.",
    "NO_LAYOUTS": "Add a layout if the deliverable is expected to include printable output.",
    "LAYOUT_WITHOUT_MAP_FRAME": "Add a map frame or remove the unused layout.",
}


def merged_policy(override: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    policy = copy.deepcopy(DEFAULT_POLICY)
    if not override:
        return policy
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(policy.get(key), MutableMapping):
            policy[key].update(value)
        else:
            policy[key] = value
    validate_policy(policy)
    return policy


def load_policy(path: Optional[Path]) -> Dict[str, Any]:
    if path is None:
        return merged_policy()
    with path.open("r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Policy root must be a JSON object.")
    return merged_policy(data)


def validate_policy(policy: Mapping[str, Any]) -> None:
    for code, severity in policy.get("checks", {}).items():
        if severity not in SEVERITY_ORDER and severity != "off":
            raise ValueError("Unsupported severity for {}: {}".format(code, severity))
    for severity, weight in policy.get("score_weights", {}).items():
        if severity not in SEVERITY_ORDER:
            raise ValueError("Unsupported score severity: {}".format(severity))
        if not isinstance(weight, (int, float)) or weight < 0:
            raise ValueError("Score weights must be non-negative numbers.")
    for key in ("allowed_source_roots", "blocked_source_roots"):
        if not isinstance(policy.get(key, []), list):
            raise ValueError("{} must be a JSON array.".format(key))
    if policy.get("fail_on") not in FAIL_ON_CHOICES:
        raise ValueError(
            "Unsupported fail_on value: {} (expected one of {})".format(
                policy.get("fail_on"), ", ".join(FAIL_ON_CHOICES)
            )
        )


def finding_fingerprint(code: str, context: Mapping[str, Any]) -> str:
    payload = json.dumps(
        {"code": code, "context": context},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def make_finding(
    policy: Mapping[str, Any],
    code: str,
    default_severity: str,
    message: str,
    **context: Any
) -> Optional[Dict[str, Any]]:
    severity = policy.get("checks", {}).get(code, default_severity)
    if severity == "off":
        return None
    result: Dict[str, Any] = {
        "code": code,
        "severity": severity,
        "message": message,
        "recommendation": RECOMMENDATIONS.get(code, "Review this finding before release."),
        "fingerprint": finding_fingerprint(code, context),
    }
    if context:
        result["context"] = context
    return result


def add_finding(
    findings: List[Dict[str, Any]],
    policy: Mapping[str, Any],
    code: str,
    severity: str,
    message: str,
    **context: Any
) -> None:
    finding = make_finding(policy, code, severity, message, **context)
    if finding is not None:
        findings.append(finding)


def is_windows_path(value: str) -> bool:
    return len(value) >= 3 and value[1:3] in (":\\", ":/")


def path_segments(value: str) -> List[str]:
    """Split a data source into components, ignoring the separator style used."""
    return [segment for segment in value.replace("/", "\\").split("\\") if segment]


def source_kind(source: str) -> str:
    lowered = source.lower().strip()
    if lowered.startswith(("http://", "https://")):
        return "web-service"
    if lowered.startswith("\\\\") or lowered.startswith("//"):
        return "unc"
    if lowered.startswith(("memory\\", "in_memory\\")):
        return "memory"

    # Geodatabase sources are recognised by a whole path component, not by a
    # substring: "city.gdb\\roads" is a geodatabase layer, whereas
    # "old.gdb_backup\\roads.shp" is a shapefile that merely mentions ".gdb".
    segments = path_segments(lowered)
    if any(segment.endswith(".sde") for segment in segments):
        return "enterprise-geodatabase"
    if any(segment.endswith(".gdb") for segment in segments):
        return "file-geodatabase"
    if segments:
        leaf = segments[-1]
        if leaf.endswith(".shp"):
            return "shapefile"
        if leaf.endswith(RASTER_EXTENSIONS):
            return "raster"
    if is_windows_path(source):
        return "local-file"
    return "other"


def normalize_path(value: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.expandvars(os.path.expanduser(value))))


def path_under_root(source: str, root: str) -> bool:
    try:
        source_path = normalize_path(source)
        root_path = normalize_path(root)
        return os.path.commonpath([source_path, root_path]) == root_path
    except (OSError, ValueError):
        return False


def iter_layers(map_obj: Any) -> Iterable[Any]:
    """Yield ArcPy's flattened layer listing once, including nested layers."""
    for layer in map_obj.listLayers():
        yield layer


def safe_data_source(item: Any) -> Optional[str]:
    try:
        if item.supports("DATASOURCE"):
            value = item.dataSource
            return str(value) if value else None
    except Exception:
        return None
    return None


def safe_spatial_reference(arcpy: Any, item: Any) -> Optional[str]:
    try:
        description = arcpy.Describe(item)
        spatial_reference = getattr(description, "spatialReference", None)
        name = getattr(spatial_reference, "name", None)
        if name and name not in ("Unknown", "Unknown Coordinate System"):
            return str(name)
        return "Unknown"
    except Exception:
        return None


def _check_source_policy(
    source: str,
    policy: Mapping[str, Any],
    findings: List[Dict[str, Any]],
    context: Dict[str, Any],
) -> None:
    kind = source_kind(source)
    if kind == "unc":
        add_finding(
            findings,
            policy,
            "UNC_SOURCE_PATH",
            "warning",
            "Data source depends on a UNC network path.",
            data_source=source,
            **context
        )
    elif kind in (
        "enterprise-geodatabase",
        "file-geodatabase",
        "shapefile",
        "raster",
        "local-file",
    ):
        add_finding(
            findings,
            policy,
            "ABSOLUTE_SOURCE_PATH",
            "warning",
            "Data source is bound to an absolute local path.",
            data_source=source,
            **context
        )

    blocked = [root for root in policy.get("blocked_source_roots", []) if path_under_root(source, root)]
    if blocked:
        add_finding(
            findings,
            policy,
            "SOURCE_IN_BLOCKED_ROOT",
            "error",
            "Data source is located under a blocked root.",
            data_source=source,
            blocked_root=blocked[0],
            **context
        )

    allowed_roots = policy.get("allowed_source_roots", [])
    if allowed_roots and kind not in ("web-service", "memory", "other"):
        if not any(path_under_root(source, root) for root in allowed_roots):
            add_finding(
                findings,
                policy,
                "SOURCE_OUTSIDE_ALLOWED_ROOTS",
                "warning",
                "Data source is outside all allowed roots.",
                data_source=source,
                **context
            )


def _audit_source_item(
    item: Any,
    item_type: str,
    map_name: str,
    arcpy: Any,
    policy: Mapping[str, Any],
    findings: List[Dict[str, Any]],
) -> Dict[str, Any]:
    name = str(getattr(item, "longName", None) or getattr(item, "name", "Unnamed item"))
    broken = bool(getattr(item, "isBroken", False))
    source = safe_data_source(item)
    item_report: Dict[str, Any] = {"name": name, "broken": broken}
    context = {"map": map_name, item_type: name}

    if source:
        kind = source_kind(source)
        item_report.update({"data_source": source, "source_kind": kind})
        _check_source_policy(source, policy, findings, context)
        if kind not in ("web-service", "memory", "other"):
            try:
                source_exists = bool(arcpy.Exists(source))
            except Exception:
                source_exists = None
            item_report["source_exists"] = source_exists
            if source_exists is False:
                add_finding(
                    findings,
                    policy,
                    "MISSING_DATA_SOURCE",
                    "error",
                    "ArcPy cannot resolve the data source.",
                    data_source=source,
                    **context
                )

    if broken:
        code = "BROKEN_LAYER" if item_type == "layer" else "BROKEN_TABLE"
        add_finding(
            findings,
            policy,
            code,
            "error",
            "ArcGIS Pro reports this {} as broken.".format(item_type),
            **context
        )

    spatial_reference = safe_spatial_reference(arcpy, item)
    if spatial_reference:
        item_report["spatial_reference"] = spatial_reference
        if spatial_reference == "Unknown":
            add_finding(
                findings,
                policy,
                "UNKNOWN_SPATIAL_REFERENCE",
                "warning",
                "{} has an unknown spatial reference.".format(item_type.title()),
                **context
            )
    return item_report


def _score(findings: Iterable[Mapping[str, Any]], policy: Mapping[str, Any]) -> Dict[str, Any]:
    counts = Counter(str(item["severity"]) for item in findings)
    weights = policy.get("score_weights", {})
    deductions = sum(counts.get(level, 0) * float(weights.get(level, 0)) for level in SEVERITY_ORDER)
    value = max(0, min(100, int(round(100 - deductions))))
    grade = "A" if value >= 90 else "B" if value >= 80 else "C" if value >= 70 else "D" if value >= 60 else "F"
    status = "fail" if counts.get("error", 0) else "review" if counts.get("warning", 0) else "pass"
    return {
        "errors": counts.get("error", 0),
        "warnings": counts.get("warning", 0),
        "info": counts.get("info", 0),
        "status": status,
        "health_score": value,
        "grade": grade,
    }


def audit_project(project_path: Path, arcpy: Any, policy: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    active_policy = merged_policy(policy)
    if not project_path.exists():
        raise FileNotFoundError("Project file does not exist: {}".format(project_path))
    if project_path.suffix.lower() != ".aprx":
        raise ValueError("Expected an .aprx project file: {}".format(project_path))

    project = arcpy.mp.ArcGISProject(str(project_path))
    maps = list(project.listMaps())
    layouts = list(project.listLayouts())
    findings: List[Dict[str, Any]] = []
    map_reports: List[Dict[str, Any]] = []
    layout_reports: List[Dict[str, Any]] = []
    total_layers = 0
    total_tables = 0
    total_sources = 0

    if not maps:
        add_finding(findings, active_policy, "NO_MAPS", "error", "Project contains no maps.")

    for map_obj in maps:
        map_name = str(getattr(map_obj, "name", "Unnamed map"))
        layers = list(iter_layers(map_obj))
        tables = list(map_obj.listTables()) if hasattr(map_obj, "listTables") else []
        content_layers = [layer for layer in layers if not getattr(layer, "isGroupLayer", False)]
        total_layers += len(content_layers)
        total_tables += len(tables)

        # A map holding nothing but empty group layers still ships no content.
        if not content_layers and not tables:
            add_finding(
                findings,
                active_policy,
                "EMPTY_MAP",
                "warning",
                "Map contains no layers or standalone tables.",
                map=map_name,
            )

        layer_names = [str(getattr(layer, "name", "Unnamed layer")) for layer in layers]
        duplicate_layer_names = sorted(name for name, count in Counter(layer_names).items() if count > 1)
        if duplicate_layer_names:
            add_finding(
                findings,
                active_policy,
                "DUPLICATE_LAYER_NAMES",
                "warning",
                "Map contains duplicate layer names.",
                map=map_name,
                names=duplicate_layer_names,
            )

        table_names = [str(getattr(table, "name", "Unnamed table")) for table in tables]
        duplicate_table_names = sorted(name for name, count in Counter(table_names).items() if count > 1)
        if duplicate_table_names:
            add_finding(
                findings,
                active_policy,
                "DUPLICATE_TABLE_NAMES",
                "warning",
                "Map contains duplicate standalone table names.",
                map=map_name,
                names=duplicate_table_names,
            )

        layer_reports: List[Dict[str, Any]] = []
        table_reports: List[Dict[str, Any]] = []
        spatial_references = set()
        for layer in layers:
            if getattr(layer, "isGroupLayer", False):
                continue
            layer_report = _audit_source_item(
                layer, "layer", map_name, arcpy, active_policy, findings
            )
            if layer_report.get("data_source"):
                total_sources += 1
            if layer_report.get("spatial_reference") not in (None, "Unknown"):
                spatial_references.add(layer_report["spatial_reference"])
            layer_reports.append(layer_report)

        for table in tables:
            table_report = _audit_source_item(
                table, "table", map_name, arcpy, active_policy, findings
            )
            if table_report.get("data_source"):
                total_sources += 1
            table_reports.append(table_report)

        if len(spatial_references) > 1:
            add_finding(
                findings,
                active_policy,
                "MIXED_SPATIAL_REFERENCES",
                "warning",
                "Map layers use more than one known spatial reference.",
                map=map_name,
                spatial_references=sorted(spatial_references),
            )

        map_reports.append(
            {
                "name": map_name,
                "layer_count": len(layer_reports),
                "table_count": len(table_reports),
                "layers": layer_reports,
                "tables": table_reports,
            }
        )

    if not layouts:
        # require_layout is a convenience switch for the common case: it lifts the
        # default "info" severity to "warning". An explicit non-default severity
        # still wins, so a team can either silence the check with "off" or harden
        # it to "error" without the flag silently undoing that decision.
        no_layout_policy = active_policy
        effective = active_policy.get("checks", {}).get(
            "NO_LAYOUTS", DEFAULT_POLICY["checks"]["NO_LAYOUTS"]
        )
        if active_policy.get("require_layout") and effective == DEFAULT_POLICY["checks"]["NO_LAYOUTS"]:
            no_layout_policy = copy.deepcopy(active_policy)
            no_layout_policy["checks"]["NO_LAYOUTS"] = "warning"
        add_finding(
            findings,
            no_layout_policy,
            "NO_LAYOUTS",
            "info",
            "Project contains no layouts.",
        )

    for layout in layouts:
        layout_name = str(getattr(layout, "name", "Unnamed layout"))
        try:
            map_frames = list(layout.listElements("MAPFRAME_ELEMENT"))
        except Exception:
            map_frames = []
        if not map_frames:
            add_finding(
                findings,
                active_policy,
                "LAYOUT_WITHOUT_MAP_FRAME",
                "warning",
                "Layout contains no map frame.",
                layout=layout_name,
            )
        layout_reports.append(
            {
                "name": layout_name,
                "map_frame_count": len(map_frames),
                "map_frames": [str(getattr(frame, "name", "Unnamed map frame")) for frame in map_frames],
            }
        )

    findings.sort(key=lambda item: (SEVERITY_ORDER[item["severity"]], item["code"], item["fingerprint"]))
    summary = _score(findings, active_policy)
    return {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project": str(project_path.resolve()),
        "project_name": project_path.name,
        "summary": summary,
        "metrics": {
            "maps": len(maps),
            "layouts": len(layouts),
            "layers": total_layers,
            "tables": total_tables,
            "data_sources": total_sources,
        },
        "maps": map_reports,
        "layouts": layout_reports,
        "findings": findings,
    }


def _baseline_health_score(baseline: Mapping[str, Any]) -> float:
    score = baseline.get("summary", {}).get("health_score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ValueError("Baseline is missing a numeric summary.health_score.")
    return float(score)


def compare_with_baseline(report: Dict[str, Any], baseline: Mapping[str, Any]) -> Dict[str, Any]:
    # Fail closed: a baseline missing its score or its fingerprints would still
    # produce a delta, but every current finding would silently look brand new.
    baseline_findings = baseline.get("findings", [])
    if not isinstance(baseline_findings, list):
        raise ValueError("Baseline findings must be a JSON array.")
    without_fingerprint = [
        item for item in baseline_findings if not isinstance(item, dict) or not item.get("fingerprint")
    ]
    if without_fingerprint:
        raise ValueError(
            "Baseline has {} finding(s) without a fingerprint; refusing to guess which findings were resolved.".format(
                len(without_fingerprint)
            )
        )
    baseline_score = _baseline_health_score(baseline)

    current_by_id = {item["fingerprint"]: item for item in report.get("findings", [])}
    baseline_by_id = {item["fingerprint"]: item for item in baseline_findings}
    current_ids = set(current_by_id)
    baseline_ids = set(baseline_by_id)
    report["delta"] = {
        "new_findings": [current_by_id[key] for key in sorted(current_ids - baseline_ids)],
        "resolved_findings": [baseline_by_id[key] for key in sorted(baseline_ids - current_ids)],
        "unchanged_findings": len(current_ids & baseline_ids),
        "health_score_change": int(report["summary"]["health_score"] - baseline_score),
    }
    return report


def redact_report(report: Mapping[str, Any]) -> Dict[str, Any]:
    user_profile = os.path.expanduser("~")

    def redact(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [redact(item) for item in value]
        if isinstance(value, str) and user_profile:
            normalized_value = value.replace("/", "\\")
            normalized_home = user_profile.replace("/", "\\").rstrip("\\")
            lowered_home = normalized_home.lower()
            lowered_value = normalized_value.lower()
            # Match on a separator boundary so a home of "C:\Users\ann" does not
            # swallow "C:\Users\anna\data" and rewrite it into a broken path.
            if lowered_home:
                if lowered_value == lowered_home:
                    return "%USERPROFILE%"
                if lowered_value.startswith(lowered_home + "\\"):
                    return "%USERPROFILE%" + normalized_value[len(normalized_home):]
        return value

    return redact(copy.deepcopy(report))


def render_text(report: Mapping[str, Any]) -> str:
    summary = report["summary"]
    metrics = report["metrics"]
    lines = [
        "ArcGIS Pro Guardian: {}".format(report["project_name"]),
        "Status: {status} | score={health_score}/100 ({grade}) | errors={errors} warnings={warnings} info={info}".format(**summary),
        "Inventory: maps={maps} layouts={layouts} layers={layers} tables={tables} sources={data_sources}".format(**metrics),
    ]
    for finding in report.get("findings", []):
        context = finding.get("context", {})
        context_text = ", ".join("{}={}".format(key, value) for key, value in context.items())
        suffix = " ({})".format(context_text) if context_text else ""
        lines.append("- [{severity}] {code}: {message}{suffix}".format(suffix=suffix, **finding))
    delta = report.get("delta")
    if delta:
        lines.append(
            "Baseline: new={} resolved={} unchanged={} score_change={:+d}".format(
                len(delta["new_findings"]),
                len(delta["resolved_findings"]),
                delta["unchanged_findings"],
                delta["health_score_change"],
            )
        )
    return "\n".join(lines) + "\n"


def render_markdown(report: Mapping[str, Any]) -> str:
    summary = report["summary"]
    metrics = report["metrics"]
    lines = [
        "# ArcGIS Pro Guardian report",
        "",
        "**Project:** `{}`  ".format(report["project_name"]),
        "**Status:** `{}` · **Health:** {}/100 ({})  ".format(summary["status"], summary["health_score"], summary["grade"]),
        "**Inventory:** {} maps · {} layouts · {} layers · {} tables · {} sources".format(
            metrics["maps"], metrics["layouts"], metrics["layers"], metrics["tables"], metrics["data_sources"]
        ),
        "",
        "## Findings",
        "",
    ]
    if not report.get("findings"):
        lines.append("No findings. The project passed the configured policy.")
    else:
        lines.extend(["| Severity | Code | Finding | Recommendation |", "|---|---|---|---|"])
        for item in report["findings"]:
            message = str(item["message"]).replace("|", "\\|")
            recommendation = str(item["recommendation"]).replace("|", "\\|")
            lines.append("| {} | `{}` | {} | {} |".format(item["severity"], item["code"], message, recommendation))
    if report.get("delta"):
        delta = report["delta"]
        lines.extend(
            [
                "",
                "## Baseline delta",
                "",
                "- New findings: {}".format(len(delta["new_findings"])),
                "- Resolved findings: {}".format(len(delta["resolved_findings"])),
                "- Unchanged findings: {}".format(delta["unchanged_findings"]),
                "- Health score change: {:+d}".format(delta["health_score_change"]),
            ]
        )
    return "\n".join(lines) + "\n"


def render_html(report: Mapping[str, Any]) -> str:
    summary = report["summary"]
    metrics = report["metrics"]
    status_class = html.escape(str(summary["status"]))
    rows = []
    for item in report.get("findings", []):
        context = item.get("context", {})
        context_text = " · ".join("{}={}".format(key, value) for key, value in context.items())
        rows.append(
            "<tr><td><span class='pill {sev}'>{sev}</span></td><td><code>{code}</code></td>"
            "<td><strong>{message}</strong><small>{context}</small></td><td>{recommendation}</td></tr>".format(
                sev=html.escape(str(item["severity"])),
                code=html.escape(str(item["code"])),
                message=html.escape(str(item["message"])),
                context=html.escape(context_text),
                recommendation=html.escape(str(item["recommendation"])),
            )
        )
    if not rows:
        rows.append("<tr><td colspan='4' class='empty'>No findings. The project passed the configured policy.</td></tr>")

    delta_card = ""
    if report.get("delta"):
        delta = report["delta"]
        delta_card = """
        <section class="delta">
          <h2>Baseline delta</h2>
          <div class="metric-grid">
            <div><b>{new}</b><span>New</span></div>
            <div><b>{resolved}</b><span>Resolved</span></div>
            <div><b>{unchanged}</b><span>Unchanged</span></div>
            <div><b>{change:+d}</b><span>Score change</span></div>
          </div>
        </section>""".format(
            new=len(delta["new_findings"]),
            resolved=len(delta["resolved_findings"]),
            unchanged=delta["unchanged_findings"],
            change=delta["health_score_change"],
        )

    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ArcGIS Pro Guardian · {project}</title>
<style>
:root{{--ink:#10231b;--muted:#5e6f66;--paper:#f4f7f4;--card:#fff;--line:#dce5df;--green:#19724a;--lime:#b8e348;--red:#c9363e;--amber:#b26a00}}
*{{box-sizing:border-box}}body{{margin:0;background:linear-gradient(135deg,#eef7f1,#f7f4ea);color:var(--ink);font:15px/1.55 Inter,Segoe UI,Arial,sans-serif}}
.shell{{max-width:1180px;margin:auto;padding:48px 24px 72px}}header{{display:flex;justify-content:space-between;gap:24px;align-items:end;margin-bottom:24px}}
.eyebrow{{font-size:12px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:var(--green)}}header>div:first-child{{min-width:0}}h1{{font-size:clamp(30px,5vw,58px);line-height:1;margin:.2em 0;overflow-wrap:anywhere}}
.path{{color:var(--muted);word-break:break-all}}.score{{min-width:180px;border-radius:24px;padding:22px;color:#fff;background:#173c2d;box-shadow:0 14px 36px #173c2d22}}
.score b{{display:block;font-size:46px;line-height:1}}.score span{{opacity:.8}}.status-pass{{border-top:8px solid var(--lime)}}.status-review{{border-top:8px solid var(--amber)}}.status-fail{{border-top:8px solid var(--red)}}
.metric-grid{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:24px 0}}.metric-grid div{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px}}
.metric-grid b{{display:block;font-size:28px}}.metric-grid span{{color:var(--muted)}}section{{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:24px;margin-top:18px;box-shadow:0 12px 30px #173c2d0c}}
h2{{margin-top:0}}table{{width:100%;border-collapse:collapse}}th,td{{padding:13px 10px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}}th{{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}}
small{{display:block;color:var(--muted);margin-top:4px;word-break:break-all}}code{{font:12px/1.4 Consolas,monospace}}.pill{{display:inline-block;border-radius:99px;padding:4px 9px;font-size:12px;font-weight:800}}.error{{background:#ffe6e7;color:var(--red)}}.warning{{background:#fff0cf;color:var(--amber)}}.info{{background:#e8f2ed;color:var(--green)}}.empty{{text-align:center;color:var(--muted);padding:36px}}footer{{color:var(--muted);margin-top:22px;font-size:12px}}
@media(max-width:760px){{header{{display:block}}.score{{margin-top:18px}}.metric-grid{{grid-template-columns:repeat(2,1fr)}}
table,tbody,tr,td{{display:block;width:100%}}thead{{display:none}}tbody tr{{padding:14px 0;border-bottom:1px solid var(--line)}}td{{border:0;padding:6px 0;overflow-wrap:anywhere}}td:before{{display:block;margin-bottom:3px;color:var(--muted);font-size:10px;font-weight:800;letter-spacing:.1em;text-transform:uppercase}}td:nth-child(1):before{{content:'Severity'}}td:nth-child(2):before{{content:'Code'}}td:nth-child(3):before{{content:'Finding'}}td:nth-child(4):before{{content:'Recommendation'}}}}
</style></head><body><main class="shell">
<header><div><div class="eyebrow">ArcGIS Pro Guardian</div><h1>{project}</h1><div class="path">{path}</div></div>
<div class="score status-{status}"><b>{score}</b><span>Health score · Grade {grade}</span></div></header>
<div class="metric-grid">
<div><b>{errors}</b><span>Errors</span></div><div><b>{warnings}</b><span>Warnings</span></div><div><b>{maps}</b><span>Maps</span></div><div><b>{layers}</b><span>Layers</span></div><div><b>{sources}</b><span>Sources</span></div>
</div>
{delta}
<section><h2>Findings</h2><table><thead><tr><th>Severity</th><th>Code</th><th>Finding</th><th>Recommendation</th></tr></thead><tbody>{rows}</tbody></table></section>
<footer>Generated {generated} · Schema {schema} · Guardian {version}</footer>
</main></body></html>""".format(
        project=html.escape(str(report["project_name"])),
        path=html.escape(str(report["project"])),
        status=status_class,
        score=summary["health_score"],
        grade=html.escape(str(summary["grade"])),
        errors=summary["errors"],
        warnings=summary["warnings"],
        maps=metrics["maps"],
        layers=metrics["layers"],
        sources=metrics["data_sources"],
        delta=delta_card,
        rows="".join(rows),
        generated=html.escape(str(report["generated_at"])),
        schema=report["schema_version"],
        version=html.escape(str(report["tool_version"])),
    )


def render_report(report: Mapping[str, Any], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if output_format == "markdown":
        return render_markdown(report)
    if output_format == "html":
        return render_html(report)
    return render_text(report)


def should_fail(report: Mapping[str, Any], fail_on: str) -> bool:
    summary = report["summary"]
    if fail_on == "never":
        return False
    if fail_on == "warning":
        return bool(summary["errors"] or summary["warnings"])
    return bool(summary["errors"])
