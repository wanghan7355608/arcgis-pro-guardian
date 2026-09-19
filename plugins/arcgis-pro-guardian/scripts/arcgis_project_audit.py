#!/usr/bin/env python
"""Read-only ArcGIS Pro project audit for Codex.

Run with the Python interpreter shipped with ArcGIS Pro. The script only reads
the .aprx through arcpy.mp and emits a stable JSON report or a human summary.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def issue(code: str, severity: str, message: str, **context: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "code": code,
        "severity": severity,
        "message": message,
    }
    if context:
        result["context"] = context
    return result


def is_probably_local_path(source: str) -> bool:
    """Return whether a data source looks like a Windows filesystem path."""
    return (
        len(source) >= 3 and source[1:3] == ":\\"
    ) or source.startswith("\\\\")


def iter_layers(map_obj: Any) -> Iterable[Any]:
    """Yield top-level and nested layers without depending on layer type names."""
    for layer in map_obj.listLayers():
        yield layer
        if getattr(layer, "isGroupLayer", False):
            for child in layer.listLayers():
                yield child


def safe_data_source(layer: Any) -> Optional[str]:
    try:
        if layer.supports("DATASOURCE"):
            value = layer.dataSource
            return str(value) if value else None
    except Exception:
        return None
    return None


def safe_spatial_reference(arcpy: Any, layer: Any) -> Optional[str]:
    try:
        description = arcpy.Describe(layer)
        spatial_reference = getattr(description, "spatialReference", None)
        name = getattr(spatial_reference, "name", None)
        if name and name not in ("Unknown", "Unknown Coordinate System"):
            return str(name)
        return "Unknown"
    except Exception:
        return None


def audit_project(project_path: Path, arcpy: Any) -> Dict[str, Any]:
    if not project_path.exists():
        raise FileNotFoundError("Project file does not exist: {}".format(project_path))
    if project_path.suffix.lower() != ".aprx":
        raise ValueError("Expected an .aprx project file: {}".format(project_path))

    project = arcpy.mp.ArcGISProject(str(project_path))
    maps = list(project.listMaps())
    layouts = list(project.listLayouts())
    findings: List[Dict[str, Any]] = []
    map_reports: List[Dict[str, Any]] = []

    if not maps:
        findings.append(issue("NO_MAPS", "error", "Project contains no maps."))

    for map_obj in maps:
        map_name = str(getattr(map_obj, "name", "Unnamed map"))
        layers = list(iter_layers(map_obj))
        layer_names = [str(getattr(layer, "name", "Unnamed layer")) for layer in layers]
        duplicate_names = sorted(
            name for name, count in Counter(layer_names).items() if count > 1
        )
        if duplicate_names:
            findings.append(
                issue(
                    "DUPLICATE_LAYER_NAMES",
                    "warning",
                    "Map contains duplicate layer names.",
                    map=map_name,
                    names=duplicate_names,
                )
            )
        if not layers:
            findings.append(
                issue("EMPTY_MAP", "warning", "Map contains no layers.", map=map_name)
            )

        layer_reports: List[Dict[str, Any]] = []
        spatial_references = set()
        for layer in layers:
            layer_name = str(getattr(layer, "name", "Unnamed layer"))
            if getattr(layer, "isGroupLayer", False):
                continue
            broken = bool(getattr(layer, "isBroken", False))
            source = safe_data_source(layer)
            layer_report: Dict[str, Any] = {
                "name": layer_name,
                "broken": broken,
            }
            if source:
                layer_report["data_source"] = source
                if is_probably_local_path(source):
                    layer_report["portability"] = "machine-bound-path"
                    findings.append(
                        issue(
                            "ABSOLUTE_SOURCE_PATH",
                            "warning",
                            "Layer uses an absolute or UNC data source path.",
                            map=map_name,
                            layer=layer_name,
                            data_source=source,
                        )
                    )
                try:
                    source_exists = bool(arcpy.Exists(source))
                except Exception:
                    source_exists = None
                if source_exists is False:
                    findings.append(
                        issue(
                            "MISSING_DATA_SOURCE",
                            "error",
                            "ArcPy cannot resolve the layer data source.",
                            map=map_name,
                            layer=layer_name,
                            data_source=source,
                        )
                    )
            if broken:
                findings.append(
                    issue(
                        "BROKEN_LAYER",
                        "error",
                        "ArcGIS Pro reports this layer as broken.",
                        map=map_name,
                        layer=layer_name,
                    )
                )

            spatial_reference = safe_spatial_reference(arcpy, layer)
            if spatial_reference:
                layer_report["spatial_reference"] = spatial_reference
                spatial_references.add(spatial_reference)
                if spatial_reference == "Unknown":
                    findings.append(
                        issue(
                            "UNKNOWN_SPATIAL_REFERENCE",
                            "warning",
                            "Layer has an unknown spatial reference.",
                            map=map_name,
                            layer=layer_name,
                        )
                    )
            layer_reports.append(layer_report)

        if len(spatial_references) > 1:
            findings.append(
                issue(
                    "MIXED_SPATIAL_REFERENCES",
                    "warning",
                    "Map layers use more than one spatial reference.",
                    map=map_name,
                    spatial_references=sorted(spatial_references),
                )
            )

        map_reports.append(
            {
                "name": map_name,
                "layer_count": len(layer_reports),
                "layers": layer_reports,
            }
        )

    if not layouts:
        findings.append(issue("NO_LAYOUTS", "info", "Project contains no layouts."))

    counts = Counter(item["severity"] for item in findings)
    return {
        "project": str(project_path.resolve()),
        "project_name": project_path.name,
        "maps": map_reports,
        "layout_count": len(layouts),
        "summary": {
            "errors": counts.get("error", 0),
            "warnings": counts.get("warning", 0),
            "info": counts.get("info", 0),
            "status": "fail" if counts.get("error", 0) else "review" if counts.get("warning", 0) else "pass",
        },
        "findings": findings,
    }


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="Path to a saved .aprx project")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a human summary")
    parser.add_argument("--strict", action="store_true", help="Exit 1 when warnings or errors exist")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        import arcpy  # type: ignore
    except ImportError as exc:
        print("ArcPy is unavailable. Run with ArcGIS Pro's Python interpreter.", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 2

    try:
        report = audit_project(Path(args.project), arcpy)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:  # ArcPy exceptions vary by Pro release.
        print("ArcGIS Pro could not open the project: {}".format(exc), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        summary = report["summary"]
        print("ArcGIS Pro Guardian: {}".format(report["project_name"]))
        print("Status: {status} | errors={errors} warnings={warnings} info={info}".format(**summary))
        for finding in report["findings"]:
            context = finding.get("context", {})
            suffix = " ({})".format(", ".join("{}={}".format(k, v) for k, v in context.items())) if context else ""
            print("- [{severity}] {code}: {message}{suffix}".format(suffix=suffix, **finding))

    if args.strict and (report["summary"]["errors"] or report["summary"]["warnings"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
