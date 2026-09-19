# Changelog

## Unreleased

- Added a reproducible ArcPy Before/After case study with redacted JSON and HTML evidence.
- Added a 66-second H.264 demo, a three-minute Chinese interview pitch, and technical Q&A notes.
- Added `docs/case-study/reproduce.py`, which rebuilds both case-study projects from ArcGIS Pro's blank project and fails when the result no longer matches the published numbers. Committed `.aprx` files are no longer required to reproduce the case.
- Added `fail_on` as a validated policy key so a team policy can carry its own delivery gate; an explicit `--fail-on` still wins, and `--strict` wins over both.
- Fixed mobile overflow for long ArcGIS Pro project names in HTML reports.
- Fixed `fail_on` in a policy file being parsed but never read, which made the policy's delivery gate silently inert.
- Fixed `require_layout: true` overwriting an explicit `NO_LAYOUTS` severity, which re-enabled a check a team had set to `off`.
- Fixed baseline comparison treating a baseline without `summary.health_score` as zero, which reported every finding as new instead of failing closed.
- Fixed profile-path redaction matching on a bare prefix, which rewrote a sibling directory such as `C:\Users\anna` when the profile was `C:\Users\ann`.
- Fixed geodatabase detection matching anywhere in the path, so a shapefile under `old.gdb_backup` is no longer reported as a file geodatabase.
- Fixed an empty map going unreported when it contained nothing but empty group layers.

## 0.2.0

- Added a native ArcGIS Pro Python Toolbox with an **Audit ArcGIS Pro Project** geoprocessing tool.
- Added 0–100 project health scoring and letter grades.
- Added layer, table, layout, source-type, and policy-root checks.
- Added JSON policy overrides with per-check severity controls.
- Added text, JSON, Markdown, and standalone HTML reports.
- Added baseline comparison for new and resolved findings.
- Added profile-path redaction and configurable CI failure thresholds.
- Added ArcPy-free unit tests and GitHub Actions CI.

## 0.1.0

- Initial read-only ArcGIS Pro project audit.
