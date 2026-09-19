# ArcGIS Pro Guardian

ArcGIS Pro Guardian is a local-first Codex plugin for reviewing saved ArcGIS Pro projects before handoff, publication, or migration to another machine.

It runs a read-only ArcPy audit over a saved `.aprx` and reports:

- broken layers and unresolved data sources;
- absolute/UNC paths that make a project machine-bound;
- duplicate layer names;
- unknown or mixed spatial references;
- empty maps and missing layouts as review context.

The niche is deliberate: existing public ArcGIS AI projects mostly expose geoprocessing tools or live MCP control. This plugin focuses on the preflight gap between “the project opens on my machine” and “the project is safe to hand off.” A global claim that no one has ever built the same idea is not provable; this repository records the specific scope and implementation so the differentiation is concrete.

## Requirements

- ArcGIS Pro with its bundled Python environment;
- a saved `.aprx` file;
- Codex with local plugin support.

## Run the audit directly

```powershell
$arcgisPython = 'C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe'
& $arcgisPython .\plugins\arcgis-pro-guardian\scripts\arcgis_project_audit.py `
  --project 'C:\path\to\project.aprx' --json
```

The script never saves the project or rewrites data sources. Use `--strict` in CI-style checks to return exit code `1` for warnings or errors.

## Install from this repository

```powershell
codex plugin marketplace add <owner>/arcgis-pro-guardian
codex plugin add arcgis-pro-guardian@personal
```

The marketplace manifest is at `.agents/plugins/marketplace.json`. Replace `<owner>` after creating the GitHub repository.

## License

MIT
