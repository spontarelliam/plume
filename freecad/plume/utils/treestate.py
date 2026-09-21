"""
Keep the state of a tree view (open folders, selected item) across a reload of its model.

Pure python, no Qt import: works with any view/model providing the usual Qt API
(rowCount, index, isExpanded, expand...), and a model with a filePath(index) method.
"""
import os


def collect_expanded(view, model, parent):
    """Paths of the folders currently open in the view (only the visible branches are walked)"""
    paths = set()
    for row in range(model.rowCount(parent)):
        index = model.index(row, 0, parent)
        if view.isExpanded(index):
            paths.add(model.filePath(index))
            paths |= collect_expanded(view, model, index)
    return paths


def restore_expanded(view, model, parent, paths):
    """Open again the folders whose path is in paths (those that still exist)"""
    if not paths:
        return

    for row in range(model.rowCount(parent)):
        index = model.index(row, 0, parent)
        if model.filePath(index) in paths:
            view.expand(index)
            restore_expanded(view, model, index, paths)


def find_index(model, parent, path):
    """Index of the item with this path, or None"""
    for row in range(model.rowCount(parent)):
        index = model.index(row, 0, parent)
        item_path = model.filePath(index)
        if item_path == path:
            return index
        if path.startswith(item_path + os.sep):
            found = find_index(model, index, path)
            if found is not None:
                return found
    return None
