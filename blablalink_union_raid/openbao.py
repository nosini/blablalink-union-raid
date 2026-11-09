# SPDX-License-Identifier: AGPL-3.0-or-later

"""Read the write token from OpenBao instead of RAID_WRITE_TOKEN.

Optional: it is used when BLABLALINK_UNION_RAID=openbao is set. The token is
the key RAID_WRITE_TOKEN of the KV secret whose path (below the `kv` mount) is
in BLABLALINK_UNION_RAID_OPENBAO_PATH; there is no default path.

The login is the one the homelab deployments use: Pocket ID through OpenBao's
OIDC role `deploy`, cached for hours, handled by that repository's
`scripts/openbao-session`. That helper runs a command with BAO_ADDR and
BAO_TOKEN set. Either run this tool under it:

    openbao-session -- blablalink-union-raid push ...

or set BLABLALINK_UNION_RAID_OPENBAO_SESSION to the helper's path, and this
tool starts itself under it when it has no session yet. The OIDC code is not
copied here, so a fix to the login applies to both.
"""

import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

SWITCHES = ("BLABLALINK_UNION_RAID", "BLABLALINK-UNION-RAID")
HELPER = "BLABLALINK_UNION_RAID_OPENBAO_SESSION"
PATH = "BLABLALINK_UNION_RAID_OPENBAO_PATH"
MOUNT = "kv"
KEY = "RAID_WRITE_TOKEN"


class OpenBaoError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def selected(environ=os.environ):
    """True if OpenBao is asked for. The hyphenated name is accepted too:
    a shell can't export it, but `env 'BLABLALINK-UNION-RAID=openbao'` can.
    """
    value = next((environ[name] for name in SWITCHES if environ.get(name)), "")
    if value in ("", "env"):
        return False
    if value != "openbao":
        raise OpenBaoError(f"BLABLALINK_UNION_RAID={value!r}: use 'openbao' "
                           "to read the token from OpenBao")
    return True


def build_opener(cafile=None):
    context = ssl.create_default_context(cafile=cafile)
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}), NoRedirect(),
        urllib.request.HTTPSHandler(context=context))


def read_secret(address, token, opener, path, mount=MOUNT, key=KEY):
    """The value of `key` in kv/<path>; errors never show a response body."""
    url = urllib.parse.urlsplit(address)
    if (url.scheme != "https" or not url.hostname or url.username
            or url.password or url.path not in ("", "/") or url.query
            or url.fragment):
        raise OpenBaoError("BAO_ADDR must be an https address without "
                           "credentials or a path")
    if not re.fullmatch(r"[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*", path):
        raise OpenBaoError("invalid secret path")
    request = urllib.request.Request(
        f"{address.rstrip('/')}/v1/{mount}/data/{path}",
        headers={"X-Vault-Token": token})
    try:
        with opener.open(request, timeout=30) as response:
            value = json.load(response)["data"]["data"].get(key)
    except urllib.error.HTTPError as exc:
        raise OpenBaoError({
            403: "OpenBao refused the read: the session may be expired or "
                 "lack access (run the helper with --logout, then retry)",
            404: f"no secret at {mount}/{path}"}.get(
                exc.code, f"OpenBao read failed (HTTP {exc.code})")) from None
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise OpenBaoError("OpenBao read failed: connection or response "
                           "problem") from None
    if not isinstance(value, str) or not value.strip():
        raise OpenBaoError(f"{mount}/{path} has no {key} value")
    return value


def start_session(environ, execute=os.execv):
    """Replace this process by the same command under the login helper."""
    helper = environ.get(HELPER)
    if not helper or not os.path.isfile(helper):
        raise OpenBaoError(
            "no OpenBao session. Run this command under the helper, e.g. "
            "`~/Git/homelab-infra/scripts/openbao-session -- "
            "blablalink-union-raid push ...`, or set "
            f"{HELPER} to the helper's path")
    python = sys.executable
    execute(python, [python, helper, "--", python, "-m",
                     "blablalink_union_raid", *sys.argv[1:]])


def write_token(environ=os.environ, opener=None, execute=os.execv):
    """The write token from OpenBao, signing in first if there is no session."""
    path = environ.get(PATH)
    if not path:  # before any login
        raise OpenBaoError(f"set {PATH} to the secret's path below the "
                           f"{MOUNT} mount")
    address, token = environ.get("BAO_ADDR"), environ.get("BAO_TOKEN")
    if not (address and token):
        start_session(environ, execute)
        raise OpenBaoError("the OpenBao session did not start")
    return read_secret(address, token,
                       opener or build_opener(environ.get("BAO_CACERT")), path)
