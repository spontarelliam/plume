"""
Find the FreeCAD files an .FCStd file depends on (the files holding the parts of an
assembly...), without opening it in FreeCAD: the links to other documents are stored
in the Document.xml of the archive, as XLink entries with a path relative to the file.

Pure python, no FreeCAD or Qt import.
"""
import html
import os
import re
import zipfile

_XLINK_FILE = re.compile(r"<XLink\w*\s[^>]*?\bfile=\"([^\"]*)\"")


def linked_files(path):
    """Absolute paths of the files directly linked by this .FCStd file (empty list if unreadable)"""
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("Document.xml").decode("utf-8", errors="replace")
    except (OSError, KeyError, zipfile.BadZipFile):
        return []

    folder = os.path.dirname(os.path.abspath(path))
    found = []
    for name in _XLINK_FILE.findall(xml):
        name = html.unescape(name)
        if not name:
            continue
        linked = os.path.normpath(os.path.join(folder, name))
        if linked not in found:
            found.append(linked)
    return found


def dependencies(path):
    """
    Absolute paths of all the existing files this .FCStd file depends on, directly or not
    (a part used by a sub-assembly is included). The file itself is not part of the result.
    """
    root = os.path.normpath(os.path.abspath(path))
    result = []
    seen = {root}
    todo = [root]
    while todo:
        for linked in linked_files(todo.pop()):
            if linked in seen or not os.path.isfile(linked):
                continue
            seen.add(linked)
            result.append(linked)
            todo.append(linked)
    return result
