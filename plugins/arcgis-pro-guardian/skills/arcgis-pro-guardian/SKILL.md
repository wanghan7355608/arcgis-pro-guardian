---
name: arcgis-pro-guardian
description: Audit saved ArcGIS Pro .aprx projects with ArcPy for broken layers, missing data sources, portability risks, duplicate names, and spatial-reference drift before handoff or publishing.
---

# ArcGIS Pro Guardian

Use this skill when a user asks to inspect an ArcGIS Pro project, find broken layers, check whether a project can move to another machine, review map data quality, or prepare an `.aprx` for handoff. The audit is read-only: never save, repair, re-path, or overwrite the project unless the user explicitly asks for that separate change.

## What it checks

- broken layers and tables reported by ArcGIS Pro;
- data sources that ArcPy cannot resolve;
- absolute local paths and UNC paths that reduce portability;
- duplicate layer/table names within a map;
- unknown or mixed spatial references within a map;
- maps without layers and projects without maps.

## Workflow

1. Resolve the exact saved `.aprx` path. If the user only refers to the currently open unsaved project, explain that an external ArcPy process cannot inspect `CURRENT`; ask for a saved copy or an explicit export.
2. Run the bundled audit script with the ArcGIS Pro Python interpreter. On this Windows installation the usual interpreter is:

   ```powershell
   $arcgisPython = 'C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe'
   & $arcgisPython '<plugin-root>\scripts\arcgis_project_audit.py' --project '<path-to-project.aprx>' --json
   ```

3. Summarize findings by severity (`error`, `warning`, `info`) and include the map/layer/table context. Keep the raw JSON available when another tool needs to consume it.
4. Distinguish a missing source from a source that is merely outside the current machine's access. Do not claim a source is permanently lost based on one local check.
5. If a repair is requested, report the proposed mutations first and wait for explicit confirmation before changing paths or saving the `.aprx`.

## Interpretation rules

- `error`: the project has a broken or unresolved source, or no usable map was found.
- `warning`: the project may work locally but has portability or consistency risk.
- `info`: context that helps review the project but is not itself a failure.

The script intentionally does not inspect or transmit feature data. It reads project metadata through ArcPy and prints paths that ArcGIS Pro exposes. Redact paths before sharing audit output outside the local machine.

## Failure handling

- If `import arcpy` fails, report the exact interpreter path used and ask the user to run the command from an ArcGIS Pro Python environment.
- If the project is locked or currently unsaved, do not work around the lock by copying or modifying files silently.
- If a layer is a web service or query layer, treat its URI as a source identifier rather than testing it as a local filesystem path.
