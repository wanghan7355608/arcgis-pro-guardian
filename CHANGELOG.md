# Changelog

## 0.3.0

- Fixed baseline fingerprints colliding when one map holds two items with the same name, which dropped one of them from the delta while the score still counted both. Repeat occurrences are now disambiguated, and only repeat occurrences, so a project without duplicates keeps the exact fingerprints its existing baselines stored.
- Fixed a malformed policy structure such as `"checks": "none"` raising `AttributeError`, which escaped the command line's error handling as a traceback and exit code 1 — the code documented to mean a finding reached the fail-on threshold.
- Fixed unknown policy keys and unknown check codes being merged in and then silently ignored, so a misspelled check name no longer leaves a team believing a check was disabled or hardened when nothing changed.
- Fixed `require_layout` accepting a non-boolean value, where `"false"` read as true and promoted `NO_LAYOUTS` to a warning.
- Fixed the Python Toolbox's **Fail Tool On** parameter displaying `Error` while the run honoured the policy file's `fail_on`, so a project could meet or miss its gate with no visible reason. Deferring to the policy is now an explicit `Policy` choice.
- Fixed `render_report` falling back to a text report for an unrecognised format, which wrote plain text behind an `.html` name.
- Fixed an allowed-roots policy being bypassed by a source Guardian could not classify. A relative source such as `data\roads.dbf` carries no drive letter, so `source_kind` fell through to `other`, which the allow-list exempted alongside remote and in-memory sources — a source the policy could not place passed by default, producing no finding at all. Values with no separator anywhere, such as a query layer's SQL, are still exempt because they are not locations.
- Added `GUARDIAN_DEBUG=1`, which prints a traceback when an audit fails so a bug inside Guardian is distinguishable from a project ArcPy cannot open.
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
