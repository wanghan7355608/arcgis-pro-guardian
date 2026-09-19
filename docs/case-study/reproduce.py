"""Rebuild the Before/After case study from scratch and verify the documented result.

Run this with the Python interpreter bundled with ArcGIS Pro:

    & 'C:\\Program Files\\ArcGIS\\Pro\\bin\\Python\\envs\\arcgispro-py3\\python.exe' `
        docs\\case-study\\reproduce.py

The script starts from a blank ArcGIS Pro project, audits it (Before), builds a
corrected copy, audits that against the Before report as a baseline (After), and
then asserts that the numbers match the ones published in README.zh-CN.md. Any
mismatch exits non-zero, so the case study cannot quietly drift away from its
evidence.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import arcpy

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "plugins" / "arcgis-pro-guardian" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from guardian_core import (  # noqa: E402
    audit_project,
    compare_with_baseline,
    load_policy,
    redact_report,
    render_report,
)

POLICY_PATH = Path(__file__).resolve().parent / "interview-policy.json"
LAYOUT_TEMPLATE = Path(
    r"C:\Program Files\ArcGIS\Pro\Resources\LayoutTemplates\en-US\Minimal A3 Landscape.pagx"
)

# ArcGIS Pro ships a blank project that a new project is copied from. The path is
# an install detail that varies by release, so every candidate is tried and the
# caller can always pass their own blank project instead.
BLANK_PROJECT_CANDIDATES = (
    Path(r"C:\Program Files\ArcGIS\Pro\Resources\ArcToolBox\Services\routingservices\data\Blank.aprx"),
    Path(r"C:\Program Files\ArcGIS\Pro\Resources\ArcToolBox\Templates\Blank.aprx"),
)

FEATURE_CLASS_NAME = "review_sites"
SITES = (
    ((116.3974, 39.9093), "Interview venue"),
    ((116.4074, 39.9193), "Backup venue"),
    ((116.3874, 39.8993), "Data checkpoint"),
)

EXPECTED_BEFORE = {
    "health_score": 88,
    "grade": "B",
    "status": "review",
    "errors": 0,
    "warnings": 2,
    "codes": {"EMPTY_MAP", "NO_LAYOUTS"},
    "maps": 1,
    "layouts": 0,
    "layers": 0,
}
EXPECTED_AFTER = {
    "health_score": 100,
    "grade": "A",
    "status": "pass",
    "errors": 0,
    "warnings": 0,
    "codes": {"ABSOLUTE_SOURCE_PATH"},
    "maps": 2,
    "layouts": 1,
    "layers": 2,
    "resolved": 2,
    "score_change": 12,
}


def find_blank_project(override: Path | None) -> Path:
    if override is not None:
        if not override.exists():
            raise FileNotFoundError("Blank project not found: {}".format(override))
        return override
    for candidate in BLANK_PROJECT_CANDIDATES:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "Could not find the blank ArcGIS Pro project. Create one in ArcGIS Pro "
        "(New Project) and pass --blank-project <path>."
    )


def build_before(blank_project: Path, case_dir: Path) -> Path:
    """A saved project with one empty map and no layout."""
    before = case_dir / "Before.aprx"
    shutil.copyfile(str(blank_project), str(before))
    project = arcpy.mp.ArcGISProject(str(before))
    del project
    return before


def build_after(before_project: Path, case_dir: Path) -> Path:
    """The same project with a layout, a projected feature class, and layers."""
    after = case_dir / "After.aprx"
    gdb = case_dir / "guardian_demo.gdb"
    arcpy.management.CreateFileGDB(str(case_dir), gdb.name)
    feature_class = gdb / FEATURE_CLASS_NAME
    arcpy.management.CreateFeatureclass(
        str(gdb), FEATURE_CLASS_NAME, "POINT", spatial_reference=arcpy.SpatialReference(4326)
    )
    arcpy.management.AddField(str(feature_class), "site_name", "TEXT", field_length=80)
    with arcpy.da.InsertCursor(str(feature_class), ["SHAPE@XY", "site_name"]) as cursor:
        for shape, name in SITES:
            cursor.insertRow((shape, name))

    project = arcpy.mp.ArcGISProject(str(before_project))
    project.importDocument(str(LAYOUT_TEMPLATE))
    # The A3 template carries its own map. Clear every map's contents so each one
    # holds only the explicitly projected feature class, which is what removes the
    # unknown-spatial-reference finding the template's basemap would otherwise add.
    for map_obj in project.listMaps():
        for layer in list(map_obj.listLayers()):
            map_obj.removeLayer(layer)
        added = map_obj.addDataFromPath(str(feature_class))
        added.name = "Review Sites"
    project.saveACopy(str(after))
    del project
    return after


def summarize(report: dict) -> dict:
    summary = report["summary"]
    return {
        "health_score": summary["health_score"],
        "grade": summary["grade"],
        "status": summary["status"],
        "errors": summary["errors"],
        "warnings": summary["warnings"],
        "codes": {finding["code"] for finding in report["findings"]},
        "maps": report["metrics"]["maps"],
        "layouts": report["metrics"]["layouts"],
        "layers": report["metrics"]["layers"],
    }


def verify(label: str, actual: dict, expected: dict) -> list[str]:
    failures = []
    for key, want in expected.items():
        got = actual.get(key)
        if got != want:
            failures.append("{}: {} = {!r}, expected {!r}".format(label, key, got, want))
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(REPO_ROOT / "docs" / "case-study" / "reproduced"))
    parser.add_argument("--blank-project", default=None, help="Override the blank .aprx to start from")
    args = parser.parse_args(argv)

    case_dir = Path(args.output).resolve()
    if case_dir.exists():
        shutil.rmtree(case_dir)
    case_dir.mkdir(parents=True)

    policy = load_policy(POLICY_PATH)
    blank = find_blank_project(Path(args.blank_project) if args.blank_project else None)
    print("Blank project : {}".format(blank))
    print("Output        : {}".format(case_dir))

    before_project = build_before(blank, case_dir)
    before = audit_project(before_project, arcpy, policy)
    (case_dir / "before.json").write_text(
        render_report(redact_report(before), "json"), encoding="utf-8"
    )
    (case_dir / "before.html").write_text(
        render_report(redact_report(before), "html"), encoding="utf-8"
    )

    after_project = build_after(before_project, case_dir)
    after = audit_project(after_project, arcpy, policy)
    compare_with_baseline(after, before)
    (case_dir / "after.json").write_text(render_report(redact_report(after), "json"), encoding="utf-8")
    (case_dir / "after.html").write_text(render_report(redact_report(after), "html"), encoding="utf-8")

    before_actual = summarize(before)
    after_actual = summarize(after)
    after_actual["resolved"] = len(after["delta"]["resolved_findings"])
    after_actual["score_change"] = after["delta"]["health_score_change"]

    print("\nBefore: {health_score}/100 ({grade}) {status}, {errors} errors".format(**before_actual))
    print("After : {health_score}/100 ({grade}) {status}, {errors} errors".format(**after_actual))
    print("Delta : +{score_change} points, {resolved} resolved".format(**after_actual))

    failures = verify("before", before_actual, EXPECTED_BEFORE) + verify("after", after_actual, EXPECTED_AFTER)
    if failures:
        print("\nFAIL: the reproduced result does not match the published case study.")
        for line in failures:
            print("  - {}".format(line))
        return 1
    print("\nPASS: reproduced result matches the published case study.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
