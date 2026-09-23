import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS = Path(__file__).parents[1] / "plugins" / "arcgis-pro-guardian" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from guardian_core import (  # noqa: E402
    _score,
    audit_project,
    compare_with_baseline,
    merged_policy,
    redact_report,
    render_html,
    render_report,
    should_fail,
    source_kind,
    validate_policy,
)


class FakeSpatialReference:
    def __init__(self, name):
        self.name = name


class FakeDescription:
    def __init__(self, name):
        self.spatialReference = FakeSpatialReference(name)


class FakeItem:
    def __init__(self, name, source=None, broken=False, spatial_reference="WGS 1984", is_group_layer=False):
        self.name = name
        self.longName = name
        self.dataSource = source
        self.isBroken = broken
        self.isGroupLayer = is_group_layer
        self.spatial_reference = spatial_reference

    def supports(self, capability):
        return capability == "DATASOURCE" and self.dataSource is not None


class FakeMap:
    def __init__(self, name, layers=None, tables=None):
        self.name = name
        self._layers = layers or []
        self._tables = tables or []

    def listLayers(self):
        return self._layers

    def listTables(self):
        return self._tables


class FakeFrame:
    name = "Main frame"


class FakeLayout:
    def __init__(self, name, frames=None):
        self.name = name
        self._frames = frames or []

    def listElements(self, element_type):
        return self._frames if element_type == "MAPFRAME_ELEMENT" else []


class FakeProject:
    def __init__(self, maps, layouts):
        self._maps = maps
        self._layouts = layouts

    def listMaps(self):
        return self._maps

    def listLayouts(self):
        return self._layouts


class FakeMP:
    def __init__(self, project):
        self._project = project

    def ArcGISProject(self, _path):
        return self._project


class FakeArcPy:
    def __init__(self, project):
        self.mp = FakeMP(project)

    @staticmethod
    def Exists(source):
        return "missing" not in source.lower()

    @staticmethod
    def Describe(item):
        return FakeDescription(item.spatial_reference)


class GuardianTests(unittest.TestCase):
    def test_source_classification(self):
        self.assertEqual(source_kind("https://example.com/FeatureServer/0"), "web-service")
        self.assertEqual(source_kind(r"\\server\share\roads.shp"), "unc")
        self.assertEqual(source_kind(r"C:\data\city.gdb\roads"), "file-geodatabase")
        self.assertEqual(source_kind(r"C:\data\terrain.tif"), "raster")

    def test_audit_finds_release_risks_and_scores_project(self):
        project = FakeProject(
            [
                FakeMap(
                    "Operations",
                    layers=[
                        FakeItem("Roads", r"C:\delivery\roads.shp"),
                        FakeItem("Missing", r"C:\delivery\missing.gdb\sites", broken=True, spatial_reference="Unknown"),
                    ],
                    tables=[FakeItem("Owners", r"\\server\share\owners.dbf")],
                )
            ],
            [FakeLayout("Overview", [FakeFrame()])],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = Path(temp_dir) / "demo.aprx"
            project_path.write_bytes(b"fake")
            report = audit_project(project_path, FakeArcPy(project), merged_policy())

        codes = {finding["code"] for finding in report["findings"]}
        self.assertIn("BROKEN_LAYER", codes)
        self.assertIn("MISSING_DATA_SOURCE", codes)
        self.assertIn("UNKNOWN_SPATIAL_REFERENCE", codes)
        self.assertIn("UNC_SOURCE_PATH", codes)
        self.assertEqual(report["summary"]["status"], "fail")
        self.assertLess(report["summary"]["health_score"], 80)
        self.assertEqual(report["metrics"]["data_sources"], 3)

    def test_baseline_diff_and_html_escape(self):
        baseline = {
            "summary": {"health_score": 70},
            "findings": [{"fingerprint": "old", "code": "OLD"}],
        }
        report = {
            "schema_version": 2,
            "tool_version": "0.2.0",
            "generated_at": "2026-01-01T00:00:00+00:00",
            "project": r"C:\data\<demo>.aprx",
            "project_name": "<demo>.aprx",
            "summary": {"errors": 0, "warnings": 1, "info": 0, "status": "review", "health_score": 94, "grade": "A"},
            "metrics": {"maps": 1, "layouts": 1, "layers": 1, "tables": 0, "data_sources": 1},
            "findings": [{"fingerprint": "new", "code": "NEW", "severity": "warning", "message": "Review <this>", "recommendation": "Fix it", "context": {}}],
        }
        compare_with_baseline(report, baseline)
        self.assertEqual(len(report["delta"]["new_findings"]), 1)
        self.assertEqual(len(report["delta"]["resolved_findings"]), 1)
        self.assertEqual(report["delta"]["health_score_change"], 24)
        rendered = render_html(report)
        self.assertIn("&lt;demo&gt;.aprx", rendered)
        self.assertNotIn("Review <this>", rendered)

    def test_require_layout_promotes_missing_layout_to_warning(self):
        project = FakeProject([FakeMap("Map", layers=[FakeItem("Roads", "https://example.test/roads")])], [])
        policy = merged_policy({"require_layout": True})
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = Path(temp_dir) / "layout-required.aprx"
            project_path.write_bytes(b"fake")
            report = audit_project(project_path, FakeArcPy(project), policy)
        no_layout = next(item for item in report["findings"] if item["code"] == "NO_LAYOUTS")
        self.assertEqual(no_layout["severity"], "warning")


    def test_fail_on_is_a_validated_policy_key(self):
        self.assertEqual(merged_policy()["fail_on"], "error")
        self.assertEqual(merged_policy({"fail_on": "never"})["fail_on"], "never")
        with self.assertRaises(ValueError):
            validate_policy({"fail_on": "sometimes"})

    def test_require_layout_does_not_override_an_explicit_severity(self):
        project = FakeProject([FakeMap("Map", layers=[FakeItem("Roads", "https://example.test/roads")])], [])
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = Path(temp_dir) / "explicit.aprx"
            project_path.write_bytes(b"fake")

            silenced = merged_policy({"require_layout": True, "checks": {"NO_LAYOUTS": "off"}})
            codes = {item["code"] for item in audit_project(project_path, FakeArcPy(project), silenced)["findings"]}
            self.assertNotIn("NO_LAYOUTS", codes)

            hardened = merged_policy({"require_layout": True, "checks": {"NO_LAYOUTS": "error"}})
            report = audit_project(project_path, FakeArcPy(project), hardened)
            no_layout = next(item for item in report["findings"] if item["code"] == "NO_LAYOUTS")
            self.assertEqual(no_layout["severity"], "error")

    def test_redact_report_matches_only_on_a_path_boundary(self):
        with mock.patch("os.path.expanduser", return_value=r"C:\Users\ann"):
            redacted = redact_report(
                {
                    "sibling": r"C:\Users\anna\data\roads.shp",
                    "nested": r"C:\Users\ann\data\roads.shp",
                    "home": r"C:\Users\ann",
                    "unrelated": r"C:\data\roads.shp",
                }
            )
        self.assertEqual(redacted["sibling"], r"C:\Users\anna\data\roads.shp")
        self.assertEqual(redacted["nested"], r"%USERPROFILE%\data\roads.shp")
        self.assertEqual(redacted["home"], "%USERPROFILE%")
        self.assertEqual(redacted["unrelated"], r"C:\data\roads.shp")

    def test_baseline_without_a_score_or_fingerprints_fails_closed(self):
        report = {"summary": {"health_score": 90}, "findings": []}
        with self.assertRaises(ValueError):
            compare_with_baseline(report, {"findings": []})
        with self.assertRaises(ValueError):
            compare_with_baseline(report, {"summary": {"health_score": 50}, "findings": [{"code": "OLD"}]})
        with self.assertRaises(ValueError):
            compare_with_baseline(report, {"summary": {"health_score": 50}, "findings": "not-a-list"})

    def test_source_kind_matches_whole_path_components(self):
        self.assertEqual(source_kind(r"C:\data\city.gdb\roads"), "file-geodatabase")
        self.assertEqual(source_kind(r"C:\data\old.gdb_backup\roads.shp"), "shapefile")
        self.assertEqual(source_kind(r"C:\data\conn.sde\roads"), "enterprise-geodatabase")
        self.assertEqual(source_kind(r"C:\data\notes.sde_backup\roads.shp"), "shapefile")
        self.assertEqual(source_kind(r"memory\roads"), "memory")

    def test_empty_map_is_detected_when_only_group_layers_are_present(self):
        project = FakeProject(
            [
                FakeMap(
                    "Grouped",
                    layers=[
                        FakeItem("Empty group", is_group_layer=True),
                        FakeItem("Nested group", is_group_layer=True),
                    ],
                )
            ],
            [FakeLayout("Overview", [FakeFrame()])],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = Path(temp_dir) / "grouped.aprx"
            project_path.write_bytes(b"fake")
            report = audit_project(project_path, FakeArcPy(project), merged_policy())
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("EMPTY_MAP", codes)
        self.assertEqual(report["metrics"]["layers"], 0)

    def test_duplicate_layer_names_still_produce_distinct_fingerprints(self):
        # Guardian reports duplicate layer names, so it has to survive them.
        # Two same-named broken layers used to share a fingerprint because the
        # context carried only the map and the name; the baseline diff keys off
        # fingerprints, so one of the two silently vanished from the delta while
        # the score still counted both.
        project = FakeProject(
            [
                FakeMap(
                    "Operations",
                    layers=[
                        FakeItem("Roads", r"C:\delivery\roads.shp", broken=True),
                        FakeItem("Roads", r"C:\delivery\roads.shp", broken=True),
                    ],
                )
            ],
            [FakeLayout("Overview", [FakeFrame()])],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = Path(temp_dir) / "duplicates.aprx"
            project_path.write_bytes(b"fake")
            report = audit_project(project_path, FakeArcPy(project), merged_policy())

        broken = [item for item in report["findings"] if item["code"] == "BROKEN_LAYER"]
        self.assertEqual(len(broken), 2)
        fingerprints = [item["fingerprint"] for item in report["findings"]]
        self.assertEqual(len(fingerprints), len(set(fingerprints)))

        # With an empty baseline every current finding must be reported as new.
        compare_with_baseline(report, {"summary": {"health_score": 100}, "findings": []})
        self.assertEqual(len(report["delta"]["new_findings"]), len(report["findings"]))

    def test_a_project_without_duplicates_keeps_its_baseline_fingerprints(self):
        # Disambiguation must only kick in on repeat, or every existing baseline
        # in the wild would read as fully resolved and fully re-added.
        project = FakeProject(
            [
                FakeMap(
                    "Operations",
                    layers=[FakeItem("Roads", r"C:\delivery\roads.shp", broken=True)],
                )
            ],
            [FakeLayout("Overview", [FakeFrame()])],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = Path(temp_dir) / "single.aprx"
            project_path.write_bytes(b"fake")
            report = audit_project(project_path, FakeArcPy(project), merged_policy())
        broken = next(item for item in report["findings"] if item["code"] == "BROKEN_LAYER")
        self.assertNotIn("occurrence", broken["context"])

    def test_malformed_policy_structure_fails_closed(self):
        # These used to raise AttributeError. The CLI catches OSError/ValueError
        # only, so a policy typo escaped as a traceback with exit code 1 -- the
        # code documented to mean "a finding reached the fail-on threshold".
        for malformed in ({"checks": "none"}, {"checks": ["NO_MAPS"]}, {"score_weights": 5}):
            with self.assertRaises(ValueError):
                merged_policy(malformed)

    def test_unknown_policy_keys_and_check_codes_are_rejected(self):
        # A misspelled key merged cleanly and was then ignored by every check,
        # so a team could believe a check was off while it still ran.
        with self.assertRaises(ValueError):
            merged_policy({"checks": {"BROKEN_LAYERS": "off"}})
        with self.assertRaises(ValueError):
            merged_policy({"cheks": {"NO_MAPS": "off"}})
        with self.assertRaises(ValueError):
            merged_policy({"require_layout": "false"})
        merged = merged_policy({"checks": {"NO_MAPS": "off"}, "require_layout": True})
        self.assertEqual(merged["checks"]["NO_MAPS"], "off")

    def test_unknown_report_format_is_rejected(self):
        with self.assertRaises(ValueError):
            render_report({"summary": {}}, "htlm")

    def test_score_boundaries_and_status(self):
        policy = merged_policy()
        self.assertEqual(_score([], policy)["health_score"], 100)
        self.assertEqual(_score([], policy)["status"], "pass")

        one_error = _score([{"severity": "error"}], policy)
        self.assertEqual(one_error["health_score"], 75)
        self.assertEqual(one_error["grade"], "C")
        self.assertEqual(one_error["status"], "fail")

        two_warnings = _score([{"severity": "warning"}] * 2, policy)
        self.assertEqual(two_warnings["health_score"], 88)
        self.assertEqual(two_warnings["grade"], "B")
        self.assertEqual(two_warnings["status"], "review")

        # Errors cost 25 each, so the score clamps at zero instead of going negative.
        many_errors = _score([{"severity": "error"}] * 8, policy)
        self.assertEqual(many_errors["health_score"], 0)
        self.assertEqual(many_errors["grade"], "F")

        # Info findings carry no weight, so they never move the score.
        self.assertEqual(_score([{"severity": "info"}] * 5, policy)["health_score"], 100)


class ExitCodeTests(unittest.TestCase):
    """The exit codes are the automation contract, so pin them down."""

    def summary(self, errors=0, warnings=0, info=0):
        return {"summary": {"errors": errors, "warnings": warnings, "info": info}}

    def test_never_suppresses_every_threshold(self):
        self.assertFalse(should_fail(self.summary(errors=3, warnings=2), "never"))

    def test_error_threshold_ignores_warnings(self):
        self.assertFalse(should_fail(self.summary(warnings=2), "error"))
        self.assertTrue(should_fail(self.summary(errors=1), "error"))

    def test_warning_threshold_fails_on_errors_or_warnings(self):
        self.assertTrue(should_fail(self.summary(errors=1), "warning"))
        self.assertTrue(should_fail(self.summary(warnings=1), "warning"))
        self.assertFalse(should_fail(self.summary(info=4), "warning"))

    def test_a_clean_report_passes_every_threshold(self):
        for threshold in ("never", "error", "warning"):
            self.assertFalse(should_fail(self.summary(), threshold))


if __name__ == "__main__":
    unittest.main()
