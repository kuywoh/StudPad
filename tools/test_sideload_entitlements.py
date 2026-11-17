import plistlib
import unittest
from pathlib import Path

from studio.validate_entitlements import REQUIRED_ENTITLEMENTS, missing_entitlements


ROOT = Path(__file__).resolve().parents[1]


class SideloadEntitlementTests(unittest.TestCase):
    def test_checked_in_plist_requests_each_capability(self):
        with (ROOT / "app" / "entitlements-sideload.plist").open("rb") as stream:
            values = plistlib.load(stream)
        self.assertEqual(missing_entitlements(values), [])

    def test_missing_or_false_capability_is_reported(self):
        values = {key: True for key in REQUIRED_ENTITLEMENTS}
        values["get-task-allow"] = False
        values.pop("com.apple.developer.kernel.increased-memory-limit")
        self.assertEqual(
            missing_entitlements(values),
            [
                "get-task-allow",
                "com.apple.developer.kernel.increased-memory-limit",
            ],
        )

    def test_bundle_identifier_is_the_documented_app_id(self):
        with (ROOT / "app" / "Info.plist").open("rb") as stream:
            info = plistlib.load(stream)
        self.assertEqual(info["CFBundleIdentifier"], "com.kuywoh.studpadstudio")


if __name__ == "__main__":
    unittest.main()

