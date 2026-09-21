import os
import json
from collections import defaultdict

from PySide.QtWidgets import QMessageBox, QInputDialog, QLineEdit

import FreeCAD as App
import FreeCADGui as Gui

from freecad.plume.pl_tools import UIPATH, ICONPATH, TRANSLATIONSPATH, translate

from freecad.plume.svn.exception import SvnException
from freecad.plume.utils.plume_inventree import PlumeInventree
from freecad.plume.utils.inventree_check import diagnose_inventree, InventreeSetupError
from freecad.plume.utils.plume_svn import PlumeSvn, PlumeSvnException
from freecad.plume.utils.selector import PlumeSelection, RepositoryEvents
from freecad.plume.utils.fc_utils import read_repo_config, write_repo_config

def catch_svn(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except (PlumeSvnException, SvnException) as e:
                App.Console.PrintMessage(f"SVN ERROR : {str(e)}")
                QMessageBox.critical(None, "SVN ERROR", str(e))
            except InventreeSetupError as e:
                App.Console.PrintMessage(f"INVENTREE ERROR : {str(e)}\n")
                QMessageBox.critical(None, "InvenTree setup", str(e))

        return wrapper


def refresh_panel(func):
    """
    For the commands that can change the state of the working copy (lock, commit...):
    once done, even if it failed, ask the Plume panel to reload its status.
    """
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        finally:
            RepositoryEvents.instance().changed.emit()

    return wrapper


class CommonCommand:
    def log(self, msg):
        App.Console.PrintMessage(f'Plume : {msg}\n')

    def get_files_from_objects(self):
        sel = Gui.Selection.getSelection()
        paths = [obj.Document.FileName for obj in sel]

        paths += [p for p in PlumeSelection.instance().getSelection() if os.path.isfile(p)]

        return list(set(paths))

    def get_related_objects(self, object):
        """
        return all related object (root included)
        """
        def traverse(root):
            if hasattr(root, "PlumeIPN"):
                yield root
            if hasattr(root, "Group"):
                for obj in root.Group:
                    if hasattr(obj, "LinkedObject"):
                        obj = obj.LinkedObject
                    yield from traverse(obj)

        return list(traverse(object))

    def get_related_paths(self, object):
        """
        return all (absolute) paths related to an object
        """
        objects = list(self.get_related_objects(object))

        return list(set([o.Document.FileName for o in objects]))

    def get_children_objects(self, object):
        l = []
        if hasattr(object, "Group"):
            for obj in object.Group:
                if hasattr(obj, "PlumeIPN"):
                    if hasattr(obj, "LinkedObject"):
                        if hasattr(obj, "PlumeID"):
                            ref_id = obj.PlumeID
                        elif hasattr(obj, "PID"):
                            ref_id = obj.PID # FrameForge Id
                        else:
                            ref_id = "?"
                        obj = obj.LinkedObject
                    l.append((ref_id, obj))

        return l

    def svn(self):
        pl_snv = None
        param = App.ParamGet("User parameter:BaseApp/Preferences/Plume")
        if not param.IsEmpty():
            wc_path = param.GetString("CurrentWorkingCopy")
            if wc_path:
                pl_snv = PlumeSvn(wc_path)
            else:
                App.Console.PrintMessage(translate("plume", f"Can't load working copy\n"))

        return pl_snv



    def stored_inventree_credentials(self, url):
        """
        Login stored for this InvenTree server: {"user", "password", "token"}, or None
        """
        param = App.ParamGet("User parameter:BaseApp/Preferences/Plume")
        raw_creds = param.GetString("InvenTree Credentials")
        creds = json.loads(raw_creds) if raw_creds != "" else {}

        return creds.get(url)

    def ask_inventree_credentials(self, url):
        """
        Ask for (and store) the login for this InvenTree server.
        Returns None, and stores nothing, if the user cancels.
        """
        user, ok = QInputDialog.getText(None, "InvenTree login", f"Username for {url}\n(leave empty to use a token only)")
        if not ok:
            return None
        password, ok = QInputDialog.getText(None, "InvenTree login", f"Password for {url}", QLineEdit.EchoMode.Password)
        if not ok:
            return None
        token, ok = QInputDialog.getText(None, "InvenTree login", f"API token for {url}\n(optional, used instead of the password)")
        if not ok:
            return None

        creds = {"user": user or None, "password": password or None, "token": token or None}

        param = App.ParamGet("User parameter:BaseApp/Preferences/Plume")
        raw_creds = param.GetString("InvenTree Credentials")
        all_creds = json.loads(raw_creds) if raw_creds != "" else {}
        all_creds[url] = creds
        param.SetString("InvenTree Credentials", json.dumps(all_creds))

        return creds

    def inventree(self, ask_credentials=True):
        """
        Connect to the InvenTree server of the current repository.

        Raises InventreeSetupError, with an explanation of what is missing or
        wrong, if it is not possible. The login is asked for if there is none
        stored yet, unless ask_credentials is False.
        """
        url = (self.config().get('inventree_url') or '').strip()
        if not url:
            raise InventreeSetupError(diagnose_inventree(url))

        creds = self.stored_inventree_credentials(url)
        if creds is None and ask_credentials:
            creds = self.ask_inventree_credentials(url)
        creds = creds or {}

        user, password, token = creds.get('user'), creds.get('password'), creds.get('token')

        if not token and not (user and password):
            # explains whether the server is fine and only the login is missing, or worse
            raise InventreeSetupError(diagnose_inventree(url))

        try:
            return PlumeInventree(url, token=token, username=user, password=password)
        except Exception as e:
            diagnosis = diagnose_inventree(url, username=user, password=password, token=token)
            if diagnosis.ok:
                raise  # nothing found: keep the original error
            raise InventreeSetupError(diagnosis) from e

    def config(self):
        param = App.ParamGet("User parameter:BaseApp/Preferences/Plume")
        if not param.IsEmpty():
            wc_path = param.GetString("CurrentWorkingCopy")
            data = read_repo_config(wc_path)
        else:
            raise ValueError('Repo Config : file .plume.json not found')

        return data

    def get_export_dir(self, abs_root_path):
        """
        get export dir from filename (in release)
        """
        svn = self.svn()
        repo_config = self.config()

        rel_path = svn.get_rel_path(abs_root_path)
        if not svn.is_release_path(rel_path):
            raise PlumeSvnException(f'{abs_root_path} is not a release path')


        (rootpath, subpath, release_name, version, revision, filename) = svn.split_release_path(rel_path)

        dest = None
        if repo_config['svn_export_mode'] == "subfolder":
            dest = os.path.join(svn.working_copy, rootpath, repo_config["svn_export_subfolder"], subpath, release_name, f'{version}.{revision}')

        else:
            dest = os.path.join(svn.working_copy, repo_config["svn_export_rootfolder"], rootpath, subpath, release_name, f'{version}.{revision}')

        return dest


