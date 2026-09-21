"""
Tests for the tree state helpers. No FreeCAD or Qt needed:

    python -m unittest discover -s tests
"""
import importlib.util
import os
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..", "freecad", "plume")

spec = importlib.util.spec_from_file_location("treestate", os.path.join(ROOT, "utils", "treestate.py"))
treestate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(treestate)

WC = os.sep + os.path.join("tmp", "wc")


class Node:
    def __init__(self, name, children=()):
        self.path = os.path.join(WC, name)
        self.children = list(children)


def tree(*nodes):
    return list(nodes)


class FakeModel:
    """Minimal stand-in for the Qt model: None is the root index, nodes are the indexes"""

    def __init__(self, top):
        self.top = top

    def rowCount(self, parent):
        return len(self.top if parent is None else parent.children)

    def index(self, row, column, parent):
        return (self.top if parent is None else parent.children)[row]

    def filePath(self, index):
        return index.path


class FakeView:
    def __init__(self):
        self.expanded = set()

    def isExpanded(self, index):
        return index.path in self.expanded

    def expand(self, index):
        self.expanded.add(index.path)


def make_top(extra_file=False):
    sub_files = [Node("proj/trunk/a.FCStd")] + ([Node("proj/trunk/new.FCStd")] if extra_file else [])
    return tree(
        Node("proj", [Node("proj/trunk", sub_files), Node("proj/releases")]),
        Node("other", [Node("other/file.txt")]),
    )


class TestTreeState(unittest.TestCase):
    def test_collect_only_open_folders(self):
        model, view = FakeModel(make_top()), FakeView()
        view.expanded = {os.path.join(WC, "proj"), os.path.join(WC, "proj/trunk")}
        self.assertEqual(treestate.collect_expanded(view, model, None), view.expanded)

    def test_collect_ignores_children_of_closed_folder(self):
        model, view = FakeModel(make_top()), FakeView()
        view.expanded = {os.path.join(WC, "proj/trunk")}  # parent 'proj' closed
        self.assertEqual(treestate.collect_expanded(view, model, None), set())

    def test_restore_after_reload_with_new_content(self):
        old_view = FakeView()
        old_view.expanded = {os.path.join(WC, "proj"), os.path.join(WC, "proj/trunk")}
        expanded = treestate.collect_expanded(old_view, FakeModel(make_top()), None)

        # the model is rebuilt: new node objects, and a new file
        new_model, new_view = FakeModel(make_top(extra_file=True)), FakeView()
        treestate.restore_expanded(new_view, new_model, None, expanded)

        self.assertEqual(new_view.expanded, old_view.expanded)

    def test_restore_ignores_removed_folders(self):
        new_view = FakeView()
        treestate.restore_expanded(new_view, FakeModel(make_top()), None, {os.path.join(WC, "gone")})
        self.assertEqual(new_view.expanded, set())

    def test_restore_nothing(self):
        new_view = FakeView()
        treestate.restore_expanded(new_view, FakeModel(make_top()), None, set())
        self.assertEqual(new_view.expanded, set())

    def test_find_index(self):
        model = FakeModel(make_top(extra_file=True))
        found = treestate.find_index(model, None, os.path.join(WC, "proj/trunk/new.FCStd"))
        self.assertIsNotNone(found)
        self.assertEqual(found.path, os.path.join(WC, "proj/trunk/new.FCStd"))

    def test_find_index_missing(self):
        model = FakeModel(make_top())
        self.assertIsNone(treestate.find_index(model, None, os.path.join(WC, "proj/trunk/nope.FCStd")))
        self.assertIsNone(treestate.find_index(model, None, os.path.join(WC, "elsewhere/x")))

    def test_find_index_does_not_confuse_prefixes(self):
        top = tree(Node("proj", [Node("proj/a.FCStd")]), Node("proj2", [Node("proj2/a.FCStd")]))
        found = treestate.find_index(FakeModel(top), None, os.path.join(WC, "proj2/a.FCStd"))
        self.assertEqual(found.path, os.path.join(WC, "proj2/a.FCStd"))


if __name__ == "__main__":
    unittest.main()
