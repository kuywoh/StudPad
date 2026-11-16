"""Regression tests for macOS framework dependencies retargeted to the iOS shim."""

import unittest

from tools.ios_retarget import SHIM, map_install_name


class FrameworkRetargetTests(unittest.TestCase):
    def test_audio_unit_paths_route_through_shim(self):
        for path in (
            "/System/Library/Frameworks/AudioUnit.framework/Versions/A/AudioUnit",
            "/System/Library/Frameworks/AudioUnit.framework/AudioUnit",
        ):
            with self.subTest(path=path):
                self.assertEqual(map_install_name(path), SHIM)

    def test_audio_toolbox_keeps_its_ios_framework_path(self):
        path = "/System/Library/Frameworks/AudioToolbox.framework/Versions/A/AudioToolbox"
        self.assertEqual(
            map_install_name(path),
            "/System/Library/Frameworks/AudioToolbox.framework/AudioToolbox",
        )


if __name__ == "__main__":
    unittest.main()
