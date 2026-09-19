"""ArcGIS Pro Python Toolbox entry point for ArcGIS Pro Guardian."""

import json
import sys
from pathlib import Path

import arcpy


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from guardian_core import (  # noqa: E402
    audit_project,
    compare_with_baseline,
    load_policy,
    redact_report,
    render_report,
    should_fail,
)


class Toolbox:
    def __init__(self):
        self.label = "ArcGIS Pro Guardian"
        self.alias = "guardian"
        self.tools = [AuditProject]


class AuditProject:
    def __init__(self):
        self.label = "Audit ArcGIS Pro Project"
        self.description = (
            "Run a read-only release-readiness audit over a saved ArcGIS Pro project, "
            "calculate a health score, and create a shareable report."
        )
        self.category = "Project Quality"
        self.canRunInBackground = False

    def getParameterInfo(self):
        project = arcpy.Parameter(
            displayName="ArcGIS Pro Project",
            name="project",
            datatype="DEFile",
            parameterType="Required",
            direction="Input",
        )
        project.filter.list = ["aprx"]

        output_report = arcpy.Parameter(
            displayName="Output Guardian Report",
            name="output_report",
            datatype="DEFile",
            parameterType="Required",
            direction="Output",
        )

        report_format = arcpy.Parameter(
            displayName="Report Format",
            name="report_format",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        report_format.filter.type = "ValueList"
        report_format.filter.list = ["HTML", "JSON", "Markdown", "Text"]
        report_format.value = "HTML"

        policy = arcpy.Parameter(
            displayName="Policy JSON (optional)",
            name="policy",
            datatype="DEFile",
            parameterType="Optional",
            direction="Input",
        )
        policy.filter.list = ["json"]

        baseline = arcpy.Parameter(
            displayName="Baseline Guardian JSON (optional)",
            name="baseline",
            datatype="DEFile",
            parameterType="Optional",
            direction="Input",
        )
        baseline.filter.list = ["json"]

        fail_on = arcpy.Parameter(
            displayName="Fail Tool On",
            name="fail_on",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        fail_on.filter.type = "ValueList"
        fail_on.filter.list = ["Error", "Warning", "Never"]
        fail_on.value = "Error"

        redact_paths = arcpy.Parameter(
            displayName="Redact User Profile Paths",
            name="redact_paths",
            datatype="GPBoolean",
            parameterType="Required",
            direction="Input",
        )
        redact_paths.value = True

        return [project, output_report, report_format, policy, baseline, fail_on, redact_paths]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        project_path = parameters[0].valueAsText
        output_report = parameters[1]
        report_format = (parameters[2].valueAsText or "HTML").lower()
        if project_path and not output_report.altered:
            extension = {"html": ".html", "json": ".json", "markdown": ".md", "text": ".txt"}[report_format]
            project = Path(project_path)
            output_report.value = str(project.with_name(project.stem + "-guardian-report" + extension))
        return

    def updateMessages(self, parameters):
        project_path = parameters[0].valueAsText
        output_path = parameters[1].valueAsText
        report_format = (parameters[2].valueAsText or "HTML").lower()
        expected_extension = {"html": ".html", "json": ".json", "markdown": ".md", "text": ".txt"}[report_format]
        if project_path and Path(project_path).suffix.lower() != ".aprx":
            parameters[0].setErrorMessage("Choose a saved ArcGIS Pro .aprx project.")
        if output_path and Path(output_path).suffix.lower() != expected_extension:
            parameters[1].setWarningMessage(
                "The selected format normally uses the {} extension.".format(expected_extension)
            )
        return

    def execute(self, parameters, messages):
        project_path = Path(parameters[0].valueAsText)
        output_path = Path(parameters[1].valueAsText)
        report_format = parameters[2].valueAsText.lower()
        policy_path = Path(parameters[3].valueAsText) if parameters[3].valueAsText else None
        baseline_path = Path(parameters[4].valueAsText) if parameters[4].valueAsText else None
        redact_paths = bool(parameters[6].value)

        messages.addMessage("Opening saved project: {}".format(project_path))
        active_policy = load_policy(policy_path)
        # An untouched Fail Tool On parameter defers to the policy file, mirroring
        # the CLI where an omitted --fail-on does the same.
        if parameters[5].altered and parameters[5].valueAsText:
            fail_on = parameters[5].valueAsText.lower()
        else:
            fail_on = str(active_policy.get("fail_on", "error"))
        report = audit_project(project_path, arcpy, active_policy)

        if baseline_path:
            with baseline_path.open("r", encoding="utf-8-sig") as handle:
                baseline = json.load(handle)
            if not isinstance(baseline, dict) or "findings" not in baseline:
                raise ValueError("Baseline is not a Guardian JSON report: {}".format(baseline_path))
            report = compare_with_baseline(report, baseline)

        emitted_report = redact_report(report) if redact_paths else report
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(render_report(emitted_report, report_format), encoding="utf-8")
        parameters[1].value = str(output_path)

        summary = report["summary"]
        messages.addMessage(
            "Guardian score: {health_score}/100 ({grade}); errors={errors}, warnings={warnings}, info={info}".format(
                **summary
            )
        )
        for finding in report["findings"]:
            line = "[{severity}] {code}: {message}".format(**finding)
            if finding["severity"] == "error":
                messages.addWarningMessage(line)
            elif finding["severity"] == "warning":
                messages.addWarningMessage(line)
            else:
                messages.addMessage(line)

        messages.addMessage("Report written: {}".format(output_path))
        if should_fail(report, fail_on):
            messages.addErrorMessage(
                "The project did not meet the '{}' delivery threshold. The report was still created.".format(fail_on)
            )
            raise arcpy.ExecuteError

    def postExecute(self, parameters):
        return
