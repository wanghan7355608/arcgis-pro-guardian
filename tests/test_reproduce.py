import contextlib
import importlib.util
import io
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "guardian_case_reproduce", ROOT / "docs" / "case-study" / "reproduce.py"
)
reproduce = importlib.util.module_from_spec(SPEC)
with mock.patch.dict(sys.modules, {"arcpy": types.ModuleType("arcpy")}):
    SPEC.loader.exec_module(reproduce)


class ReproduceOutputTests(unittest.TestCase):
    def assert_rejected(self, output):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), mock.patch.object(reproduce, "build_before") as build:
            with self.assertRaises(SystemExit) as error:
                reproduce.main(["--output", str(output)])
        self.assertEqual(error.exception.code, 2)
        self.assertIn("Output path already exists", stderr.getvalue())
        build.assert_not_called()

    def test_existing_directory_and_contents_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            marker = output / "keep.txt"
            marker.write_text("user data", encoding="utf-8")
            self.assert_rejected(output)
            self.assertEqual(marker.read_text(encoding="utf-8"), "user data")

    def test_empty_directory_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            self.assert_rejected(output)
            self.assertTrue(output.is_dir())
            self.assertEqual(list(output.iterdir()), [])

    def test_existing_file_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "keep.txt"
            output.write_text("user data", encoding="utf-8")
            self.assert_rejected(output)
            self.assertEqual(output.read_text(encoding="utf-8"), "user data")

    def test_repository_root_is_rejected(self):
        self.assert_rejected(ROOT)
        self.assertTrue((ROOT / "README.md").is_file())

    def test_dangling_symbolic_link_is_rejected_before_build(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "link-output"
            # Windows may require privileges to create a symlink. Exercise the
            # dangling-link state at the CLI seam without that prerequisite.
            with mock.patch.object(Path, "is_symlink", return_value=True):
                self.assert_rejected(output)
            self.assertFalse(output.exists())

    def test_invalid_blank_project_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "new-output"
            missing = Path(temp) / "missing.aprx"
            with self.assertRaises(FileNotFoundError):
                reproduce.main(["--output", str(output), "--blank-project", str(missing)])
            self.assertFalse(output.exists())

    def test_directory_as_blank_project_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "new-output"
            invalid_blank = Path(temp) / "directory.aprx"
            invalid_blank.mkdir()
            with self.assertRaises(FileNotFoundError):
                reproduce.main(["--output", str(output), "--blank-project", str(invalid_blank)])
            self.assertFalse(output.exists())
            self.assertTrue(invalid_blank.is_dir())

    def test_directory_created_during_validation_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "new-output"

            def create_competing_output(_override):
                output.mkdir()
                (output / "keep.txt").write_text("user data", encoding="utf-8")
                return Path(temp) / "blank.aprx"

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), mock.patch.object(
                reproduce, "find_blank_project", side_effect=create_competing_output
            ), mock.patch.object(reproduce, "build_before") as build:
                with self.assertRaises(SystemExit) as error:
                    reproduce.main(["--output", str(output)])
            self.assertEqual(error.exception.code, 2)
            self.assertEqual((output / "keep.txt").read_text(encoding="utf-8"), "user data")
            build.assert_not_called()

    def test_new_directory_completes_the_existing_report_flow(self):
        def report(expected):
            return {
                "summary": {key: expected[key] for key in ("health_score", "grade", "status", "errors", "warnings")},
                "metrics": {key: expected[key] for key in ("maps", "layouts", "layers")},
                "findings": [{"code": code} for code in expected["codes"]],
            }

        before = report(reproduce.EXPECTED_BEFORE)
        after = report(reproduce.EXPECTED_AFTER)

        def compare(current, baseline):
            current["delta"] = {"resolved_findings": [1, 2], "health_score_change": 12}

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "new-output"
            with mock.patch.object(reproduce, "find_blank_project", return_value=Path(temp) / "blank.aprx"), \
                mock.patch.object(reproduce, "build_before", return_value=output / "Before.aprx") as build_before, \
                mock.patch.object(reproduce, "build_after", return_value=output / "After.aprx") as build_after, \
                mock.patch.object(reproduce, "audit_project", side_effect=[before, after]), \
                mock.patch.object(reproduce, "compare_with_baseline", side_effect=compare), \
                mock.patch.object(reproduce, "redact_report", side_effect=lambda value: value), \
                mock.patch.object(reproduce, "render_report", return_value="report"), \
                contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(reproduce.main(["--output", str(output)]), 0)
            build_before.assert_called_once_with(Path(temp) / "blank.aprx", output)
            build_after.assert_called_once_with(output / "Before.aprx", output)
            self.assertEqual(
                {path.name for path in output.iterdir()},
                {"before.json", "before.html", "after.json", "after.html"},
            )


if __name__ == "__main__":
    unittest.main()
