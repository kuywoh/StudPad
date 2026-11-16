import os
import shutil
import stat
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ZipResourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.executable = Path(cls.temp.name) / "zip_resources_cli"
        compiler = shutil.which("cc") or shutil.which("clang")
        if not compiler:
            raise unittest.SkipTest("C compiler unavailable")
        subprocess.run(
            [
                compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                "-I", str(ROOT / "app"),
                str(ROOT / "app" / "zip_resources.c"),
                str(ROOT / "tools" / "zip_resources_cli.c"),
                "-lz", "-o", str(cls.executable),
            ],
            check=True,
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_extractor(self, entries):
        directory = tempfile.mkdtemp()
        archive = Path(directory) / "studio.zip"
        destination = Path(directory) / "resources"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
            for info, data in entries:
                output.writestr(info, data)
        result = subprocess.run(
            [str(self.executable), str(archive), str(destination), "RobloxStudio.app"],
            capture_output=True,
            text=True,
        )
        return directory, destination, result

    def test_extracts_only_resources_and_verifies_files(self):
        directory, destination, result = self.run_extractor(
            [
                ("RobloxStudio.app/Contents/Resources/AppSettings.xml", b"<settings/>"),
                ("RobloxStudio.app/Contents/Resources/Fonts/Regular.otf", b"font-data"),
                ("RobloxStudio.app/Contents/MacOS/RobloxStudio", b"not extracted"),
                ("Other.app/Contents/Resources/Ignore.txt", b"not extracted"),
            ]
        )
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (destination / "AppSettings.xml").read_bytes(),
            b"<settings/>",
        )
        self.assertEqual(
            (destination / "Fonts" / "Regular.otf").read_bytes(),
            b"font-data",
        )
        self.assertFalse((destination / "RobloxStudio").exists())
        self.assertFalse((destination.parent / "escape.txt").exists())

    def test_extracts_posix_filename_characters(self):
        directory, destination, result = self.run_extractor(
            [
                ("RobloxStudio.app/Contents/Resources/Assets/variant:dark.dat", b"colon"),
                ("RobloxStudio.app/Contents/Resources/Assets/control\tname.dat", b"control"),
            ]
        )
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((destination / "Assets" / "variant:dark.dat").read_bytes(), b"colon")
        self.assertEqual((destination / "Assets" / "control\tname.dat").read_bytes(), b"control")

    def test_rejects_path_traversal(self):
        directory, _destination, result = self.run_extractor(
            [
                ("RobloxStudio.app/Contents/Resources/../../../../escape.txt", b"bad"),
                ("RobloxStudio.app/Contents/Resources/AppSettings.xml", b"ok"),
            ]
        )
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((Path(directory) / "escape.txt").exists())

    def test_rejects_symlinks_in_resource_tree(self):
        symlink = zipfile.ZipInfo("RobloxStudio.app/Contents/Resources/link")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        directory, _destination, result = self.run_extractor([(symlink, b"target")])
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("special Studio resource", result.stderr)


if __name__ == "__main__":
    unittest.main()
