"""
User settings of Plume, in a small ini file (plume.ini) in FreeCAD's user config directory.

Unlike the repository settings (.plume.json, in each working copy), these belong to the
person using FreeCAD. The file is created, with every setting documented, the first time
the workbench is loaded. Edits are picked up without restarting FreeCAD.

Pure python: FreeCAD is only imported (lazily) to find the directory and to print messages.
"""
import configparser
import os

FILENAME = "plume.ini"

TEMPLATE = """\
# Plume user settings.
# Edits are picked up without restarting FreeCAD.

[locking]
# Plume's project layout keeps the files being worked on under a "trunk" folder,
# and frozen (released) copies under "releases".
# true : "Lock files" and "Unlock files" only work on files under a "trunk" folder.
# false: any file of the working copy can be locked, whatever the folder structure.
requires_trunk = true

[working_copy]
# Show the "Switched" column in the Working Copy view.
show_switched_column = false
# Show the "External" column in the Working Copy view.
show_external_column = false
"""

DEFAULTS = {
    ("locking", "requires_trunk"): True,
    ("working_copy", "show_switched_column"): False,
    ("working_copy", "show_external_column"): False,
}


def _print(message):
    try:
        import FreeCAD as App

        App.Console.PrintMessage(f"Plume : {message}\n")
    except ImportError:
        print(f"Plume : {message}")


def default_path():
    """Where the user settings file lives"""
    import FreeCAD as App

    try:
        directory = App.getUserConfigDir()
    except AttributeError:
        directory = App.getUserAppDataDir()

    return os.path.join(directory, FILENAME)


class UserConfig:
    def __init__(self, path=None, log=None):
        """
        :param path: settings file (default: plume.ini in FreeCAD's user config directory)
        :param log: function printing a message (default: FreeCAD's report view)
        """
        self._path = path
        self._log = log or _print
        self._parser = None
        self._mtime = None
        self._warned = set()

    @property
    def path(self):
        return self._path or default_path()

    def _warn_once(self, key, message):
        if key not in self._warned:
            self._warned.add(key)
            self._log(message)

    def _load(self):
        """The parsed file, read again only if it changed on disk"""
        path = self.path

        try:
            mtime = os.stat(path).st_mtime_ns
        except OSError:
            mtime = None

        if self._parser is not None and mtime == self._mtime:
            return self._parser

        parser = configparser.ConfigParser(inline_comment_prefixes=("#", ";"))
        if mtime is not None:
            try:
                parser.read(path, encoding="utf-8")
                self._warned.discard("file")
            except (configparser.Error, UnicodeDecodeError) as e:
                parser = configparser.ConfigParser()
                self._warn_once("file", f"can't read the settings file {path} ({e}), using the defaults")

        self._parser, self._mtime = parser, mtime
        return parser

    def getboolean(self, section, option):
        default = DEFAULTS[(section, option)]

        try:
            return self._load().getboolean(section, option, fallback=default)
        except ValueError:
            self._warn_once(
                (section, option),
                f"[{section}] {option} in {self.path} must be true or false, using {str(default).lower()}",
            )
            return default

    def ensure_exists(self):
        """
        Create the settings file, with its documentation, if it doesn't exist.
        Returns True if it was created. Never raises: the settings are optional.
        """
        path = self.path
        if os.path.exists(path):
            return False

        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "x", encoding="utf-8") as f:  # 'x': never overwrite
                f.write(TEMPLATE)
        except OSError as e:
            if os.path.exists(path):
                return False  # someone else created it in the meantime

            self._log(f"can't create the settings file {path} ({e}), using the defaults")
            return False

        self._log(f"created the settings file {path}")
        return True


_config = UserConfig()


def ensure_exists():
    return _config.ensure_exists()


def lock_requires_trunk():
    """Lock/Unlock only for files under a 'trunk' folder?"""
    return _config.getboolean("locking", "requires_trunk")


def show_switched_column():
    """Show the 'Switched' column in the Working Copy view?"""
    return _config.getboolean("working_copy", "show_switched_column")


def show_external_column():
    """Show the 'External' column in the Working Copy view?"""
    return _config.getboolean("working_copy", "show_external_column")
