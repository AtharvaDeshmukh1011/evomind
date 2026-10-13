from __future__ import annotations

import hashlib
import hmac
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

API = "https://api.github.com"
COMMENT_MARKER = "<!-- evomind-risk-report -->"
_REPO_URL = re.compile(r"^(?:https?://github\.com/|git@github\.com:)([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


class GitHubError(RuntimeError):
    pass


@dataclass
class ChangedFile:
    path: str
    status: str
    previous_path: str | None = None


def parse_repo(url: str) -> tuple[str, str]:
    match = _REPO_URL.match(url.strip())
    if not match:
        raise ValueError(f"'{url}' is not a GitHub repository URL (expected https://github.com/owner/name).")
    return match.group(1), match.group(2)


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[len("sha256="):])


class GitHubClient:
    def __init__(self, token: str | None = None, timeout: float = 20.0):
        self.token = token
        self.timeout = timeout

    def _request(self, method: str, path: str, payload: dict | None = None):
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "evomind-pr-check"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = json.dumps(payload).encode() if payload is not None else None
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read()
                return json.loads(body) if body else None
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            if exc.code == 404:
                raise GitHubError(f"GitHub returned 404 for {path} — the repository or pull request does not exist, or is private and no token is configured.") from exc
            if exc.code in (401, 403):
                raise GitHubError(f"GitHub refused {method} {path} ({exc.code}) — check GITHUB_TOKEN and its permissions. {detail}") from exc
            raise GitHubError(f"GitHub API error {exc.code} on {method} {path}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise GitHubError(f"Could not reach the GitHub API: {exc.reason}") from exc

    def _paginate(self, path: str, limit: int = 3000) -> list:
        items, page = [], 1
        while len(items) < limit:
            sep = "&" if "?" in path else "?"
            batch = self._request("GET", f"{path}{sep}per_page=100&page={page}") or []
            items.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return items

    def pull_request(self, owner: str, repo: str, number: int) -> dict:
        return self._request("GET", f"/repos/{owner}/{repo}/pulls/{number}")

    def pull_request_files(self, owner: str, repo: str, number: int) -> list[ChangedFile]:
        return [
            ChangedFile(path=f["filename"], status=f["status"], previous_path=f.get("previous_filename"))
            for f in self._paginate(f"/repos/{owner}/{repo}/pulls/{number}/files")
        ]

    def upsert_comment(self, owner: str, repo: str, number: int, body: str) -> dict:
        if not self.token:
            raise GitHubError("Posting a comment needs GITHUB_TOKEN with pull-request write access.")
        for comment in self._paginate(f"/repos/{owner}/{repo}/issues/{number}/comments"):
            if COMMENT_MARKER in (comment.get("body") or ""):
                return self._request("PATCH", f"/repos/{owner}/{repo}/issues/comments/{comment['id']}", {"body": body})
        return self._request("POST", f"/repos/{owner}/{repo}/issues/{number}/comments", {"body": body})
