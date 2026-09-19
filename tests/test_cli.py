import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).parents[1] / "plugins" / "arcgis-pro-guardian" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from arcgis_project_audit import parse_args, resolve_fail_on  # noqa: E402


class FailOnResolutionTests(unittest.TestCase):
    def resolve(self, argv, policy):
        return resolve_fail_on(parse_args(argv), policy)

    def test_policy_supplies_the_threshold_when_the_flag_is_omitted(self):
        self.assertEqual(self.resolve(["--project", "x.aprx"], {"fail_on": "never"}), "never")

    def test_explicit_flag_beats_the_policy(self):
        self.assertEqual(
            self.resolve(["--project", "x.aprx", "--fail-on", "warning"], {"fail_on": "never"}),
            "warning",
        )

    def test_strict_beats_both(self):
        self.assertEqual(
            self.resolve(["--project", "x.aprx", "--fail-on", "never", "--strict"], {"fail_on": "error"}),
            "warning",
        )

    def test_error_is_the_fallback_without_a_policy_or_flag(self):
        self.assertEqual(self.resolve(["--project", "x.aprx"], {}), "error")


if __name__ == "__main__":
    unittest.main()
