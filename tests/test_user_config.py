"""
Tests for the user settings file. No FreeCAD needed:

    python -m unittest discover -s tests
"""
import importlib.util
import os
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..", "freecad", "plume")

spec = importlib.util.spec_from_file_location("user_config", os.path.join(ROOT, "utils", "user_config.py"))
user_config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(user_config)


class TestUserConfig(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "sub", "plume.ini")  # 'sub' doesn't exist yet
        self.messages = []
        self.config = user_config.UserConfig(self.path, log=self.messages.append)
        self._clock = 1_000_000_000

    def write(self, text):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text)
        # a distinct modification time, whatever the resolution of the file system
        self._clock += 10
        os.utime(self.path, ns=(self._clock * 10**9, self._clock * 10**9))

    def requires_trunk(self):
        return self.config.getboolean("locking", "requires_trunk")

    def test_missing_file_gives_default_and_is_not_created(self):
        self.assertTrue(self.requires_trunk())
        self.assertFalse(os.path.exists(self.path))
        self.assertEqual(self.messages, [])

    def test_ensure_exists_creates_documented_file(self):
        self.assertTrue(self.config.ensure_exists())
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("[locking]", content)
        self.assertIn("requires_trunk", content)
        self.assertTrue(self.requires_trunk())
        self.assertEqual(len(self.messages), 1)

    def test_switched_and_external_columns_hidden_by_default(self):
        self.assertFalse(self.config.getboolean("working_copy", "show_switched_column"))
        self.assertFalse(self.config.getboolean("working_copy", "show_external_column"))

    def test_template_matches_defaults(self):
        parser = user_config.configparser.ConfigParser(inline_comment_prefixes=("#", ";"))
        parser.read_string(user_config.TEMPLATE)
        for (section, option), default in user_config.DEFAULTS.items():
            self.assertEqual(parser.getboolean(section, option), default)

    def test_ensure_exists_never_overwrites(self):
        self.write("[locking]\nrequires_trunk = false\n")
        self.assertFalse(self.config.ensure_exists())
        self.assertFalse(self.requires_trunk())

    def test_ensure_exists_twice(self):
        self.assertTrue(self.config.ensure_exists())
        self.assertFalse(self.config.ensure_exists())

    def test_toggle_is_picked_up_without_restart(self):
        self.write("[locking]\nrequires_trunk = false\n")
        self.assertFalse(self.requires_trunk())
        self.write("[locking]\nrequires_trunk = true\n")
        self.assertTrue(self.requires_trunk())
        self.write("[locking]\nrequires_trunk = false\n")
        self.assertFalse(self.requires_trunk())

    def test_file_deleted_gives_default(self):
        self.write("[locking]\nrequires_trunk = false\n")
        self.assertFalse(self.requires_trunk())
        os.remove(self.path)
        self.assertTrue(self.requires_trunk())

    def test_boolean_spellings(self):
        for text, expected in [("true", True), ("True", True), ("yes", True), ("on", True), ("1", True),
                               ("false", False), ("No", False), ("off", False), ("0", False)]:
            self.write(f"[locking]\nrequires_trunk = {text}\n")
            self.assertEqual(self.requires_trunk(), expected, text)

    def test_inline_comment(self):
        self.write("[locking]\nrequires_trunk = false   # any folder\n")
        self.assertFalse(self.requires_trunk())

    def test_missing_option_or_section_gives_default(self):
        self.write("[locking]\n")
        self.assertTrue(self.requires_trunk())
        self.write("[other]\nx = 1\n")
        self.assertTrue(self.requires_trunk())

    def test_invalid_value_warns_once_and_gives_default(self):
        self.write("[locking]\nrequires_trunk = maybe\n")
        for _ in range(5):
            self.assertTrue(self.requires_trunk())
        self.assertEqual(len(self.messages), 1)
        self.assertIn("true or false", self.messages[0])

    def test_malformed_file_warns_once_then_recovers(self):
        self.write("requires_trunk = false\n")  # no section header
        for _ in range(3):
            self.assertTrue(self.requires_trunk())  # the default, not the value above
        self.assertEqual(len(self.messages), 1)

        self.write("[locking]\nrequires_trunk = false\n")
        self.assertFalse(self.requires_trunk())

    def test_binary_garbage_gives_default(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "wb") as f:
            f.write(b"\xff\xfe\x00\x81")
        self.assertTrue(self.requires_trunk())
        self.assertEqual(len(self.messages), 1)

    def test_unwritable_location_does_not_raise(self):
        blocker = os.path.join(self._tmp.name, "file")
        with open(blocker, "w") as f:
            f.write("x")
        config = user_config.UserConfig(os.path.join(blocker, "plume.ini"), log=self.messages.append)
        self.assertFalse(config.ensure_exists())
        self.assertTrue(config.getboolean("locking", "requires_trunk"))
        self.assertEqual(len(self.messages), 1)


if __name__ == "__main__":
    unittest.main()
