# SPDX-License-Identifier: AGPL-3.0-or-later

import io
import json
import os
import tempfile
import unittest
import urllib.error
from unittest import mock

from blablalink_union_raid import cli, openbao

ADDRESS = "https://bao.example:8200"
SECRET_PATH = "apps/union-raid/production"


class Opener:
    def __init__(self, body=None, error=None):
        self.body, self.error, self.requests = body, error, []

    def open(self, request, timeout=None):
        self.requests.append(request)
        if self.error:
            raise self.error
        return io.BytesIO(json.dumps(self.body).encode())


def secret(**data):
    return {"data": {"data": data}}


def http_error(code):
    return urllib.error.HTTPError(ADDRESS, code, "x", {},
                                   io.BytesIO(b'{"errors":["secret body"]}'))


class SelectedTest(unittest.TestCase):
    def test_off_unless_asked(self):
        self.assertFalse(openbao.selected({}))
        self.assertFalse(openbao.selected({"BLABLALINK_UNION_RAID": ""}))
        self.assertFalse(openbao.selected({"BLABLALINK_UNION_RAID": "env"}))

    def test_on_for_either_spelling(self):
        self.assertTrue(openbao.selected({"BLABLALINK_UNION_RAID": "openbao"}))
        self.assertTrue(openbao.selected({"BLABLALINK-UNION-RAID": "openbao"}))

    def test_other_values_are_an_error(self):
        with self.assertRaises(openbao.OpenBaoError):
            openbao.selected({"BLABLALINK_UNION_RAID": "vault"})


class ReadSecretTest(unittest.TestCase):
    def test_reads_the_key_with_the_session_token(self):
        opener = Opener(secret(RAID_WRITE_TOKEN="w-token"))
        self.assertEqual(
            openbao.read_secret(ADDRESS, "s.session", opener, SECRET_PATH),
            "w-token")
        request = opener.requests[0]
        self.assertEqual(
            request.full_url, f"{ADDRESS}/v1/kv/data/apps/union-raid/production")
        self.assertEqual(request.get_header("X-vault-token"), "s.session")

    def test_http_is_refused_before_any_request(self):
        opener = Opener(secret(RAID_WRITE_TOKEN="x"))
        for address in ("http://bao.example:8200", "https://u:p@bao.example",
                        "https://bao.example/path", "bao.example"):
            with self.assertRaises(openbao.OpenBaoError):
                openbao.read_secret(address, "t", opener, SECRET_PATH)
        self.assertEqual(opener.requests, [])

    def test_path_is_checked(self):
        with self.assertRaises(openbao.OpenBaoError):
            openbao.read_secret(ADDRESS, "t", Opener(), "../sys/x")

    def test_errors_say_what_to_do_and_never_show_the_body(self):
        for code, words in ((403, "session"), (404, "no secret"),
                            (500, "HTTP 500")):
            with self.assertRaises(openbao.OpenBaoError) as raised:
                openbao.read_secret(ADDRESS, "t",
                                    Opener(error=http_error(code)), SECRET_PATH)
            self.assertIn(words, str(raised.exception))
            self.assertNotIn("secret body", str(raised.exception))

    def test_missing_or_empty_key(self):
        for body in (secret(), secret(RAID_WRITE_TOKEN=""),
                     secret(RAID_WRITE_TOKEN=5), {"unexpected": 1}):
            with self.assertRaises(openbao.OpenBaoError):
                openbao.read_secret(ADDRESS, "t", Opener(body), SECRET_PATH)

    def test_the_error_lists_key_names_but_never_values(self):
        cases = ((secret(RAID_READ_TOKEN="topsecret"), "missing"),
                 (secret(RAID_WRITE_TOKEN="", OTHER="topsecret"), "empty"),
                 (secret(RAID_WRITE_TOKEN=5), "int"),
                 (secret(**{"RAID_WRITE_TOKEN ": "topsecret"}), "missing"))
        for body, kind in cases:
            with self.assertRaises(openbao.OpenBaoError) as raised:
                openbao.read_secret(ADDRESS, "t", Opener(body), SECRET_PATH)
            message = str(raised.exception)
            self.assertIn(f"({kind})", message)
            self.assertIn("keys found:", message)
            self.assertNotIn("topsecret", message)
        # a key with a stray space is visible in the quoted name
        self.assertIn("'RAID_WRITE_TOKEN '", message)

    def test_connection_failure(self):
        with self.assertRaises(openbao.OpenBaoError):
            openbao.read_secret(ADDRESS, "t", Opener(error=OSError("down")),
                                SECRET_PATH)


class WriteTokenTest(unittest.TestCase):
    def test_with_a_session_it_reads_the_secret(self):
        environ = {"BAO_ADDR": ADDRESS, "BAO_TOKEN": "s.t",
                   openbao.PATH: SECRET_PATH}
        opener = Opener(secret(RAID_WRITE_TOKEN="w-token"))
        self.assertEqual(openbao.write_token(environ, opener), "w-token")

    def test_without_a_session_or_helper_it_explains(self):
        with self.assertRaises(openbao.OpenBaoError) as raised:
            openbao.write_token({openbao.PATH: SECRET_PATH}, Opener())
        self.assertIn("openbao-session", str(raised.exception))

    def test_the_path_is_required_and_checked_before_any_login(self):
        execute = mock.Mock()
        with tempfile.NamedTemporaryFile() as helper:
            with self.assertRaises(openbao.OpenBaoError) as raised:
                openbao.write_token({openbao.HELPER: helper.name},
                                    Opener(), execute)
        self.assertIn(openbao.PATH, str(raised.exception))
        execute.assert_not_called()

    def test_the_path_comes_from_the_environment(self):
        environ = {"BAO_ADDR": ADDRESS, "BAO_TOKEN": "s.t",
                   openbao.PATH: "apps/other/path"}
        opener = Opener(secret(RAID_WRITE_TOKEN="w"))
        openbao.write_token(environ, opener)
        self.assertTrue(opener.requests[0].full_url.endswith(
            "/v1/kv/data/apps/other/path"))

    def test_without_a_session_it_restarts_under_the_helper(self):
        with tempfile.NamedTemporaryFile() as helper:
            execute = mock.Mock()
            environ = {openbao.HELPER: helper.name,
                       openbao.PATH: SECRET_PATH}
            with mock.patch("sys.argv", ["blablalink-union-raid", "push",
                                         "--season", "S47"]):
                with self.assertRaises(openbao.OpenBaoError):
                    openbao.write_token(environ, Opener(), execute)
            python, argv = execute.call_args[0]
            self.assertEqual(argv[:3], [python, helper.name, "--"])
            self.assertEqual(argv[3:], [python, "-m", "blablalink_union_raid",
                                        "push", "--season", "S47"])

    def test_a_missing_helper_file_is_not_executed(self):
        execute = mock.Mock()
        with self.assertRaises(openbao.OpenBaoError):
            openbao.write_token({openbao.HELPER: "/no/such/helper",
                                 openbao.PATH: SECRET_PATH}, Opener(), execute)
        execute.assert_not_called()


class CliTokenTest(unittest.TestCase):
    def test_env_token_is_the_default(self):
        with mock.patch.dict(os.environ, {"RAID_WRITE_TOKEN": "from-env"},
                             clear=True):
            self.assertEqual(cli.write_token(), "from-env")

    def test_openbao_wins_when_selected(self):
        env = {"RAID_WRITE_TOKEN": "from-env",
               "BLABLALINK_UNION_RAID": "openbao"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(openbao, "write_token",
                                  return_value=" from-bao\n"):
            self.assertEqual(cli.write_token(), "from-bao")

    def test_openbao_problems_become_a_clean_exit(self):
        env = {"BLABLALINK_UNION_RAID": "openbao",
               openbao.PATH: SECRET_PATH}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(SystemExit) as raised:
                cli.write_token()
        self.assertIn("openbao-session", str(raised.exception))
        env = {"BLABLALINK_UNION_RAID": "openbao"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(SystemExit) as raised:
                cli.write_token()
        self.assertIn(openbao.PATH, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
