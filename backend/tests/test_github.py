from __future__ import annotations

import hashlib
import hmac

import pytest

from evomind.integrations.github import COMMENT_MARKER, GitHubClient, GitHubError, parse_repo, verify_signature


@pytest.mark.parametrize("url,expected", [
    ("https://github.com/pallets/click", ("pallets", "click")),
    ("https://github.com/pallets/click/", ("pallets", "click")),
    ("https://github.com/pallets/click.git", ("pallets", "click")),
    ("git@github.com:foss42/apidash.git", ("foss42", "apidash")),
    ("https://github.com/some-org/my.repo", ("some-org", "my.repo")),
])
def test_parse_repo(url, expected):
    assert parse_repo(url) == expected


@pytest.mark.parametrize("url", ["https://gitlab.com/a/b", "not a url", "https://github.com/only-owner"])
def test_parse_repo_rejects_non_github(url):
    with pytest.raises(ValueError):
        parse_repo(url)


def _sign(secret, body):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_signature_accepts_the_genuine_sender():
    body = b'{"action":"opened"}'
    assert verify_signature("s3cret", body, _sign("s3cret", body))


@pytest.mark.parametrize("header", [None, "", "sha1=abc", _sign("wrong", b'{"action":"opened"}')])
def test_signature_rejects_missing_or_forged(header):
    assert not verify_signature("s3cret", b'{"action":"opened"}', header)


def test_signature_rejects_a_tampered_body():
    header = _sign("s3cret", b'{"action":"opened"}')
    assert not verify_signature("s3cret", b'{"action":"closed"}', header)


def test_no_secret_means_nothing_verifies():
    body = b"{}"
    assert not verify_signature("", body, _sign("", body))


class RecordingClient(GitHubClient):
    def __init__(self, existing_comments, token="t"):
        super().__init__(token)
        self.existing = existing_comments
        self.calls = []

    def _request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if method == "GET" and "/comments" in path:
            return self.existing if "page=1" in path else []
        return {"html_url": "https://github.com/x/y/pull/1#c"}


def test_first_report_creates_a_comment():
    client = RecordingClient([{"id": 9, "body": "LGTM"}])
    client.upsert_comment("x", "y", 1, COMMENT_MARKER + " report")
    assert client.calls[-1][0] == "POST"
    assert client.calls[-1][1] == "/repos/x/y/issues/1/comments"


def test_later_reports_update_the_same_comment():
    client = RecordingClient([{"id": 9, "body": "LGTM"}, {"id": 42, "body": COMMENT_MARKER + " old"}])
    client.upsert_comment("x", "y", 1, COMMENT_MARKER + " new")
    method, path, payload = client.calls[-1]
    assert (method, path) == ("PATCH", "/repos/x/y/issues/comments/42")
    assert payload["body"].endswith("new")


def test_posting_without_a_token_is_refused():
    with pytest.raises(GitHubError):
        RecordingClient([], token=None).upsert_comment("x", "y", 1, "body")
