"""
Tests for the FCStd dependency finder. No FreeCAD or Qt needed:

    python -m unittest discover -s tests
"""
import importlib.util
import os
import tempfile
import unittest
import zipfile

ROOT = os.path.join(os.path.dirname(__file__), "..", "freecad", "plume")

spec = importlib.util.spec_from_file_location("fcdeps", os.path.join(ROOT, "utils", "fcdeps.py"))
fcdeps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fcdeps)


class DependenciesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = os.path.realpath(self._tmp.name)

    def make(self, relpath, links=()):
        """Create an .FCStd file (a zip) whose Document.xml links to the given (relative) files"""
        path = os.path.join(self.dir, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        entries = "".join(f'<XLink file="{link}"  name="Body"/>' for link in links)
        xml = f'<Document><Properties><Property name="X"><XLink file=""  name=""/>{entries}</Property></Properties></Document>'
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("Document.xml", xml)
        return path

    def p(self, relpath):
        return os.path.join(self.dir, relpath)

    def test_no_links(self):
        self.assertEqual(fcdeps.dependencies(self.make("part.FCStd")), [])

    def test_direct_links(self):
        self.make("a.FCStd")
        self.make("b.FCStd")
        asm = self.make("asm.FCStd", ["a.FCStd", "b.FCStd", "a.FCStd"])
        self.assertEqual(fcdeps.dependencies(asm), [self.p("a.FCStd"), self.p("b.FCStd")])

    def test_nested_links_are_followed(self):
        self.make("part.FCStd")
        self.make("sub.FCStd", ["part.FCStd"])
        asm = self.make("asm.FCStd", ["sub.FCStd"])
        self.assertEqual(sorted(fcdeps.dependencies(asm)), [self.p("part.FCStd"), self.p("sub.FCStd")])

    def test_links_are_relative_to_the_linking_file(self):
        self.make("lib/part.FCStd")
        asm = self.make("proj/asm.FCStd", ["../lib/part.FCStd"])
        self.assertEqual(fcdeps.dependencies(asm), [self.p("lib/part.FCStd")])

    def test_cycle_and_self_link(self):
        a = self.make("a.FCStd", ["b.FCStd", "a.FCStd"])
        self.make("b.FCStd", ["a.FCStd"])
        self.assertEqual(fcdeps.dependencies(a), [self.p("b.FCStd")])

    def test_missing_files_are_ignored(self):
        asm = self.make("asm.FCStd", ["gone.FCStd"])
        self.assertEqual(fcdeps.dependencies(asm), [])

    def test_unreadable_file(self):
        path = os.path.join(self.dir, "broken.FCStd")
        with open(path, "w") as f:
            f.write("not a zip")
        self.assertEqual(fcdeps.dependencies(path), [])
        self.assertEqual(fcdeps.dependencies(os.path.join(self.dir, "missing.FCStd")), [])

    def test_escaped_names(self):
        self.make("R&D.FCStd")
        asm = self.make("asm.FCStd", ["R&amp;D.FCStd"])
        self.assertEqual(fcdeps.dependencies(asm), [self.p("R&D.FCStd")])


if __name__ == "__main__":
    unittest.main()
