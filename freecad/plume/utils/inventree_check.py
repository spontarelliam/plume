"""
Diagnose the connection to an InvenTree server.

Instead of failing with an obscure exception when InvenTree is missing or
misconfigured, tell the user what is wrong and what to do about it.

Pure python (requests only): no FreeCAD / Qt dependency.
"""
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

DEFAULT_TIMEOUT = 4  # seconds, this runs in the GUI thread: keep it short


@dataclass
class Diagnosis:
    # ok, no_url, bad_url, unreachable, timeout, ssl, server_error, not_inventree,
    # too_old, no_credentials, auth_failed (and, for the panel: no_working_copy, error)
    code: str
    summary: str
    details: str = ""

    @property
    def ok(self):
        return self.code == "ok"

    @property
    def message(self):
        return f"{self.summary}\n\n{self.details}" if self.details else self.summary


class InventreeSetupError(Exception):
    """InvenTree is missing or misconfigured. Carries an explanation for the user."""

    def __init__(self, diagnosis):
        super().__init__(diagnosis.message)
        self.diagnosis = diagnosis


def base_url(url):
    """
    Base url of the server (with a trailing '/'), or None if the url is not valid.
    A trailing '/api' is accepted, as in the InvenTree client.
    """
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None

    parts = [p for p in parsed.path.split("/") if p]
    if parts and parts[-1] == "api":
        parts = parts[:-1]

    path = "/".join(parts) + "/" if parts else ""
    return f"{parsed.scheme}://{parsed.netloc}/{path}"


def _request_failed(url, exc):
    """Explain a failed request (server not reachable, bad certificate, ...)"""
    if isinstance(exc, requests.exceptions.SSLError):
        return Diagnosis(
            "ssl",
            f"The HTTPS certificate of {url} could not be verified.",
            "The certificate may be self-signed, expired or issued by an authority "
            "this computer does not trust. Install a trusted certificate on the server "
            "(or add your certificate authority to the system certificate store).",
        )
    if isinstance(exc, requests.exceptions.Timeout):
        return Diagnosis(
            "timeout",
            f"The InvenTree server at {url} did not answer in time.",
            "Check that the server is running and reachable from this computer "
            "(network, VPN, firewall), then retry.",
        )
    return Diagnosis(
        "unreachable",
        f"Could not connect to an InvenTree server at {url}.",
        "Check that:\n"
        "  - the server is running (with the plume-server Docker setup: 'docker compose ps'),\n"
        "  - the host name and port in the server address are right,\n"
        "  - this computer can reach it (network, VPN, firewall).\n"
        f"({type(exc).__name__})",
    )


def _min_api_version():
    from inventree.api import InvenTreeAPI

    return InvenTreeAPI.getMinApiVersion()


def diagnose_inventree(url, username=None, password=None, token=None, timeout=DEFAULT_TIMEOUT, verify=True):
    """
    Check, step by step, that InvenTree can be used with these settings, and
    return a Diagnosis for the first thing that is wrong (code 'ok' if nothing is).
    """
    url = (url or "").strip()

    # 1. server address
    if not url:
        return Diagnosis(
            "no_url",
            "No InvenTree server is set for this repository.",
            "Enter the server address in Repository > Repository preferences > "
            "Inventree Server (for example http://localhost:8000 or https://inventree.example.com).\n"
            "If you do not have a server yet, the plume-server repository starts InvenTree "
            "and Subversion with Docker.",
        )

    base = base_url(url)
    if base is None:
        return Diagnosis(
            "bad_url",
            f"'{url}' is not a valid server address.",
            "It must start with http:// or https:// and include the host name, and the port "
            "if the server does not use the default one, for example http://localhost:8000.\n"
            "Fix it in Repository > Repository preferences > Inventree Server.",
        )

    # 2. server is there, and it is InvenTree
    api_url = base + "api/"
    try:
        response = requests.get(api_url, timeout=timeout, verify=verify)
    except requests.exceptions.RequestException as e:
        return _request_failed(base, e)

    if response.status_code != 200:
        if response.status_code == 404:
            details = (
                f"{api_url} does not exist. Check the server address (and port), and the "
                "sub-path if InvenTree sits behind a reverse proxy."
            )
        else:
            details = f"{api_url} answered with HTTP {response.status_code}. Check the server logs."
        return Diagnosis("server_error", f"The server at {base} does not answer like InvenTree.", details)

    try:
        data = response.json()
        is_inventree = isinstance(data, dict) and (
            "apiVersion" in data or str(data.get("server", "")).lower() == "inventree"
        )
        api_version = int(data.get("apiVersion", 1)) if is_inventree else None
    except (ValueError, TypeError):
        is_inventree = False

    if not is_inventree:
        return Diagnosis(
            "not_inventree",
            f"{base} answers, but it does not look like an InvenTree server.",
            "Check the server address and port: it may point to another web service, "
            "or to a page that is not the InvenTree server itself.",
        )

    minimum = _min_api_version()
    if api_version < minimum:
        return Diagnosis(
            "too_old",
            "The InvenTree server is too old for this version of Plume.",
            f"The server has API version {api_version}, Plume needs at least {minimum}. "
            "Upgrade the InvenTree server.",
        )

    # 3. credentials
    if not token and not (username and password):
        return Diagnosis(
            "no_credentials",
            f"The InvenTree server at {base} is reachable, but no login is stored for it.",
            "Click 'Set credentials...' and enter either your InvenTree username and password, "
            "or an API token created in your InvenTree user settings.",
        )

    try:
        if token:
            response = requests.get(
                api_url + "user/me/", headers={"AUTHORIZATION": f"Token {token}"}, timeout=timeout, verify=verify
            )
        else:
            response = requests.get(
                api_url + "user/me/",
                auth=requests.auth.HTTPBasicAuth(username, password),
                timeout=timeout,
                verify=verify,
            )
    except requests.exceptions.RequestException as e:
        return _request_failed(base, e)

    if response.status_code in (401, 403):
        return Diagnosis(
            "auth_failed",
            f"The InvenTree server at {base} rejected the stored login.",
            "Click 'Set credentials...' to enter it again. Check the username and password "
            "(or that the API token has not been revoked or expired).",
        )
    if response.status_code != 200:
        return Diagnosis(
            "server_error",
            f"The InvenTree server at {base} could not check the login.",
            f"{api_url}user/me/ answered with HTTP {response.status_code}. Check the server logs.",
        )

    return Diagnosis("ok", f"Connected to InvenTree at {base} (API version {api_version}).")
