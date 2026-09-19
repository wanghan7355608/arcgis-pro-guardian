<p align="center">
  <img src="plugins/arcgis-pro-guardian/assets/guardian.svg" width="112" alt="ArcGIS Pro Guardian shield">
</p>

<h1 align="center">ArcGIS Pro Guardian</h1>

<p align="center"><strong>A local-first release gate for ArcGIS Pro projects.</strong></p>

ArcGIS Pro Guardian audits a saved `.aprx`, turns hidden project risks into stable findings, assigns a 0–100 health score, compares regressions with a baseline, and produces a polished standalone HTML report. It reads project metadata through ArcPy and never saves or rewrites the project.

![ArcGIS Pro Guardian HTML report](plugins/arcgis-pro-guardian/assets/report-preview.png)

## Interview-ready case study

[![Watch the 66-second ArcGIS Pro Guardian demo](docs/interview/demo-cover.png)](docs/interview/arcgis-pro-guardian-demo-66s.mp4)

The reproducible ArcPy case starts from a saved project with an empty map and no layout, then compares a corrected copy against that baseline:

| | Before | After |
|---|---:|---:|
| Health score | 88 / B | 100 / A |
| Delivery status | Review | Pass |
| Errors / warnings | 0 / 2 | 0 / 0 |
| Baseline result | — | +12 points · 2 resolved |

- [Read the Chinese case study](docs/case-study/README.zh-CN.md)
- [Use the three-minute Chinese interview pitch](docs/interview/three-minute-pitch.zh-CN.md)
- [Practice the technical Q&A](docs/interview/qa.zh-CN.md)
- [Follow the 66-second demo script](docs/interview/demo-script.zh-CN.md)

Rebuild and verify the whole case with one command, using the Python interpreter bundled with ArcGIS Pro:

```powershell
& 'C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe' docs\case-study\reproduce.py
```

The script rebuilds both projects from ArcGIS Pro's own blank project, then asserts the result still matches the published numbers and exits non-zero if it does not. No `.aprx` needs to be committed, so the case study cannot drift away from its evidence.

The sample data is synthetic, but both reports were produced from real saved `.aprx` files using ArcGIS Pro's ArcPy runtime. Published reports redact the Windows user-profile prefix.

## Why it exists

ArcGIS automation projects usually focus on running geoprocessing tools or controlling a live Pro session. Guardian focuses on the last mile: proving that a project is healthy, portable, and ready for another person or machine.

## Highlights

| Capability | What you get |
|---|---|
| Project inventory | Maps, layouts, map frames, layers, tables, and data sources |
| Risk detection | Broken items, missing sources, machine-bound paths, duplicate names, unknown and mixed spatial references |
| Policy engine | Per-check severity overrides plus allowed and blocked source roots |
| Health score | 0–100 score, A–F grade, and pass/review/fail status |
| Baseline diff | New, resolved, and unchanged findings with score movement |
| Report formats | Text, JSON, Markdown, and a responsive single-file HTML dashboard |
| Automation | Stable exit codes and ArcPy-free tests that run on GitHub Actions |
| Privacy | Optional user-profile path redaction before sharing reports |

## Quick start

```powershell
$arcgisPython = 'C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe'
$guardian = '.\plugins\arcgis-pro-guardian\scripts\arcgis_project_audit.py'

& $arcgisPython $guardian `
  --project 'C:\GIS\Delivery\City.aprx' `
  --format html `
  --output '.\guardian-report.html' `
  --redact-paths
```

Exit codes are designed for automation:

- `0`: the configured threshold passed;
- `1`: findings reached the `--fail-on` threshold;
- `2`: ArcPy, project, baseline, policy, or output failure.

## Use it inside ArcGIS Pro

Guardian also ships as a native Python Toolbox:

`plugins/arcgis-pro-guardian/arcgis/ArcGISProGuardian.pyt`

In ArcGIS Pro, open the Catalog pane, right-click **Toolboxes**, choose **Add Toolbox**, and select that file. The **Audit ArcGIS Pro Project** tool exposes project, report format, policy, baseline, failure threshold, and path-redaction parameters in the standard Geoprocessing pane.

The tool writes the report even when a configured delivery gate fails, so the failure remains diagnosable.

## Save and compare a baseline

```powershell
& $arcgisPython $guardian `
  --project 'C:\GIS\Delivery\City.aprx' `
  --format json `
  --output '.\guardian-baseline.json' `
  --fail-on never

& $arcgisPython $guardian `
  --project 'C:\GIS\Delivery\City.aprx' `
  --baseline '.\guardian-baseline.json' `
  --format markdown `
  --output '.\guardian-delta.md'
```

Finding fingerprints are based on the check code and context, so baseline comparisons remain stable across runs.

## Team policy

Copy [`default-policy.json`](plugins/arcgis-pro-guardian/assets/default-policy.json) and customize only what your delivery process needs:

```json
{
  "checks": {
    "NO_LAYOUTS": "warning",
    "ABSOLUTE_SOURCE_PATH": "error"
  },
  "fail_on": "warning",
  "require_layout": true,
  "allowed_source_roots": ["D:\\PublishedGIS", "\\\\fileserver\\gis"],
  "blocked_source_roots": ["C:\\Users"]
}
```

Then run with `--policy .\guardian-policy.json`. The policy also carries the delivery gate, so `fail_on` there replaces the need for a `--fail-on` flag on every run. An explicit `--fail-on` still overrides the policy, and `--strict` overrides both.

Any check can be set to `error`, `warning`, `info`, or `off`. `require_layout` is a shortcut that lifts the default `NO_LAYOUTS: "info"` to `warning`; an explicit non-default severity always wins, so a team can silence the check with `off` or harden it to `error` without the flag undoing that choice. Guardian fails closed on invalid policy or baseline files instead of silently ignoring them.

## Install as a Codex plugin

```powershell
codex plugin marketplace add https://github.com/wanghan7355608/arcgis-pro-guardian
codex plugin add arcgis-pro-guardian@personal
```

The marketplace manifest lives at `.agents/plugins/marketplace.json`.

## Development

The core module has no import-time ArcPy dependency, so policy, scoring, diffing, and rendering tests run anywhere:

```powershell
python -m unittest discover -s tests -v
```

Real `.aprx` audits still require the Python interpreter bundled with ArcGIS Pro.

## Scope and safety

Guardian does not inspect feature rows, contact web services, repair paths, or save projects. Reports may include local and UNC paths; use `--redact-paths` before publishing them.

## License

MIT
