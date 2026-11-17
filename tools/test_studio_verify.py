"""Tests that every sideloaded IPA can identify its exact workflow build."""

import unittest

from studio.verify import validate_bundle_version


class BundleVersionTests(unittest.TestCase):
    def test_accepts_matching_workflow_build(self):
        validate_bundle_version({"CFBundleVersion": "54"}, "54")

    def test_rejects_mismatched_workflow_build(self):
        with self.assertRaises(SystemExit):
            validate_bundle_version({"CFBundleVersion": "48"}, "54")

    def test_rejects_missing_build_identity(self):
        with self.assertRaises(SystemExit):
            validate_bundle_version({}, "54")


if __name__ == "__main__":
    unittest.main()
