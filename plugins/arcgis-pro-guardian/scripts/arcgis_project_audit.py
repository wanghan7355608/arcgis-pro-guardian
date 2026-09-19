#!/usr/bin/env python
"""Audit a saved ArcGIS Pro project and produce release-ready reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from guardian_core import (
    audit_project,
    compare_with_baseline,
    load_policy,
    redact_report,
    render_report,
    should_fail,
)


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="Path to a saved .aprx project")
    parser.add_argument(
        "--format",
        choices=("text", "json", "markdown", "html"),
        default="text",
        help="Report format (default: text)",
    )
    parser.add_argument("--output", help="Write the report to this UTF-8 file")
    parser.add_argument("--policy", help="JSON policy file with severity and path rules")
    parser.add_argument("--baseline", help="Previous Guardian JSON report to compare against")
    parser.add_argument(
        "--fail-on",
        choices=("never", "error", "warning"),
        default=None,
        help="Exit 1 at this severity threshold (default: the policy's fail_on, else error)",
    )
    parser.add_argument(
        "--redact-paths",
        action="store_true",
        help="Replace the current user profile in emitted paths",
    )
    parser.add_argument("--json", action="store_true", help="Compatibility alias for --format json")
    parser.add_argument("--strict", action="store_true", help="Compatibility alias for --fail-on warning")
    return parser.parse_args(argv)


def load_json_report(path: Path):
    with path.open("r", encoding="utf-8-sig") as handle:
        report = json.load(handle)
    if not isinstance(report, dict) or "findings" not in report:
        raise ValueError("Baseline is not a Guardian JSON report: {}".format(path))
    score = report.get("summary", {}).get("health_score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ValueError("Baseline is missing a numeric summary.health_score: {}".format(path))
    return report


def resolve_fail_on(args: argparse.Namespace, policy: dict) -> str:
    """Precedence: --strict, an explicit --fail-on, the policy's fail_on, then error."""
    if args.strict:
        return "warning"
    if args.fail_on:
        return args.fail_on
    return str(policy.get("fail_on", "error"))


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    output_format = "json" if args.json else args.format

    try:
        policy = load_policy(Path(args.policy)) if args.policy else load_policy(None)
        baseline = load_json_report(Path(args.baseline)) if args.baseline else None
        fail_on = resolve_fail_on(args, policy)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("Configuration error: {}".format(exc), file=sys.stderr)
        return 2

    try:
        import arcpy  # type: ignore
    except ImportError as exc:
        print("ArcPy is unavailable. Run with ArcGIS Pro's Python interpreter.", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 2

    try:
        report = audit_project(Path(args.project), arcpy, policy)
        if baseline is not None:
            report = compare_with_baseline(report, baseline)
        emitted_report = redact_report(report) if args.redact_paths else report
        rendered = render_report(emitted_report, output_format)
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(rendered, encoding="utf-8")
            print("Wrote {} report: {}".format(output_format, output_path.resolve()))
        else:
            sys.stdout.write(rendered)
    except (FileNotFoundError, ValueError, RuntimeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:  # ArcPy exception types vary by Pro release.
        print("ArcGIS Pro could not audit the project: {}".format(exc), file=sys.stderr)
        return 2

    return 1 if should_fail(report, fail_on) else 0


if __name__ == "__main__":
    raise SystemExit(main())
