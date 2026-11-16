import hashlib
import plistlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from studio.write_studio_manifest import build_manifest


class StudioManifestTests(unittest.TestCase):
    def make_files(self, root: Path, url=None):
        package = root / "studio.zip"
        with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("RobloxStudio.app/Contents/Resources/AppSettings.xml", b"settings")
            archive.writestr("RobloxStudio.app/Contents/MacOS/RobloxStudio", b"ignored")
        upload = "version-abcdef1234567890"
        fetch = root / "fetch.txt"
        fetch.write_text(
            "\n".join(
                (
                    "version=0.700.0",
                    f"upload={upload}",
                    f"url={url or 'https://setup.rbxcdn.com/mac/arm64/' + upload + '-RobloxStudioApp.zip'}",
                    f"bytes={package.stat().st_size}",
                    f"sha256={hashlib.sha256(package.read_bytes()).hexdigest()}",
                    "app=/runner/fetch/RobloxStudio.app",
                )
            ),
            encoding="utf-8",
        )
        return fetch, package

    def test_manifest_pins_url_hash_and_resource_count(self):
        with tempfile.TemporaryDirectory() as directory:
            fetch, package = self.make_files(Path(directory))
            result = build_manifest(fetch, package)
            self.assertEqual(result["studio_version"], "0.700.0")
            self.assertEqual(result["resource_files"], 1)
            self.assertEqual(result["resource_bytes"], len(b"settings"))
            self.assertEqual(result["app_bundle_name"], "RobloxStudio.app")

    def test_rejects_non_roblox_download_url(self):
        with tempfile.TemporaryDirectory() as directory:
            fetch, package = self.make_files(Path(directory), url="https://example.com/studio.zip")
            with self.assertRaisesRegex(ValueError, "download URL"):
                build_manifest(fetch, package)


if __name__ == "__main__":
    unittest.main()
