---
name: arcgis-pro-guardian
description: Score, diff, and report saved ArcGIS Pro .aprx project health with ArcPy, including broken layers and tables, missing sources, portability, spatial references, layouts, configurable delivery policy, and HTML/JSON/Markdown reports.
---

# ArcGIS Pro Guardian

Use this skill for ArcGIS Pro project health checks, delivery gates, migration readiness, broken-source investigation, baseline comparisons, and audit reports. The audit is read-only: never save, repair, re-path, package, or overwrite the project unless the user explicitly requests that separate mutation.

## Capabilities

- inspect layers, standalone tables, maps, layouts, and map frames;
- classify local, UNC, geodatabase, raster, shapefile, memory, and web sources;
- detect broken or missing sources, duplicate names, and spatial-reference drift;
- apply a JSON policy with per-check severities and allowed/blocked source roots;
- calculate a 0–100 health score and letter grade;
- compare a report with a previous JSON baseline;
- emit text, JSON, Markdown, or a standalone responsive HTML dashboard;
- redact the current user-profile prefix before sharing a report;
- return stable exit codes for automation: `0` pass, `1` policy failure, `2` runtime/configuration failure.
- expose the same engine inside ArcGIS Pro through `arcgis/ArcGISProGuardian.pyt`.

## Workflow

1. Resolve the exact saved `.aprx` path. An external ArcPy process cannot inspect the unsaved state behind `ArcGISProject("CURRENT")`; ask for a saved copy when necessary.
2. Choose the report based on the request:
   - quick diagnosis: `--format text`;
   - machine-readable baseline: `--format json`;
   - issue or pull-request summary: `--format markdown`;
   - stakeholder handoff: `--format html --output <report.html>`.
3. Run the bundled CLI with the ArcGIS Pro Python interpreter:

   ```powershell
   $arcgisPython = 'C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe'
   & $arcgisPython '<plugin-root>\scripts\arcgis_project_audit.py' `
     --project '<project.aprx>' --format html --output '<report.html>' --redact-paths
   ```

4. For repeat audits, save an unredacted JSON report locally and compare the next run with `--baseline <previous.json>`. Report new and resolved findings separately.
5. For team delivery rules, copy `assets/default-policy.json`, change only the needed check severities and source roots, then pass `--policy <policy.json>`.
6. Summarize the score, error/warning counts, new regressions, and the three most actionable findings. Link the generated report when one was requested.

When the user asks to run Guardian inside ArcGIS Pro, add `arcgis/ArcGISProGuardian.pyt` from the Catalog pane and use **Audit ArcGIS Pro Project** in the Geoprocessing pane. The toolbox uses the same policy, baseline, scoring, and reporting engine as the CLI.

## Safety and interpretation

- `error` means a configured delivery gate failed; `warning` means human review is required; `info` is context.
- A missing source means ArcPy could not resolve it from this machine at audit time. Do not claim the data is permanently lost.
- Web services are identifiers, not local paths. Do not probe or authenticate to them unless the user separately requests it.
- Audit output can expose local and network paths. Use `--redact-paths` before external sharing.
- Do not alter source data, save the `.aprx`, or attempt automatic repair as part of an audit.

## Failure handling

- If `import arcpy` fails, report the interpreter path used and switch to the ArcGIS Pro Python environment.
- If the project is locked or unreadable, preserve it and report the exact ArcPy error.
- If a policy or baseline cannot be parsed, exit with code `2`; do not silently fall back to defaults.
- If a requested repair follows the audit, describe the exact project mutations and obtain confirmation before saving changes.
