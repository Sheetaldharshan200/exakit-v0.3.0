"""Downloads: HTTPS only, verified when a digest is known, one retry, a named user agent."""

from __future__ import annotations

import shutil
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol

from exakit.domain.errors import BadInput, Failed

from .digest import verify_sha256


class Downloader(Protocol):
    def fetch(self, url: str, dest: Path, *, sha256: str | None = None, token: str | None = None, what: str = "file") -> Path: ...
    def text(self, url: str, *, token: str | None = None) -> str: ...


class DownloadFailed(Failed):
    """The request did not complete. Callers that have a cached answer keep it."""


def _require_https(url: str) -> None:
    if not url.startswith("https://"):
        raise BadInput(f"Refusing to download over a non-HTTPS URL: {url}")


def http_status(url: str, *, timeout: float = 5) -> int | None:
    """The status code an HTTP GET of ``url`` answers, or None when nothing answers at all."""
    if not url.lower().startswith(("https://", "http://")):
        raise ValueError(f"unsupported URL scheme: {url}")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - http(s) only, checked above
            return int(response.status)
    except urllib.error.HTTPError as err:
        return int(err.code)
    except (urllib.error.URLError, OSError, ValueError):
        return None


class UrllibDownloader:
    """The real downloader. Standard library only."""

    def __init__(self, *, user_agent: str, connect_timeout: float = 5.0, max_time: float = 120.0) -> None:
        self.user_agent = user_agent
        self.connect_timeout = connect_timeout
        self.max_time = max_time

    def _open(self, url: str, token: str | None):
        headers = {"User-Agent": self.user_agent, "Accept": "*/*"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if not url.lower().startswith(("https://", "http://")):
            raise ValueError(f"unsupported URL scheme: {url}")
        request = urllib.request.Request(url, headers=headers)  # noqa: S310 - http(s) only, checked above
        last: Exception | None = None
        for attempt in range(2):
            try:
                return urllib.request.urlopen(request, timeout=self.connect_timeout)  # noqa: S310 - https enforced above
            except (urllib.error.URLError, TimeoutError, OSError) as err:
                last = err
                if attempt == 0:
                    time.sleep(0.5)
        raise DownloadFailed(f"Could not download {url}.", hint=str(last))

    def fetch(self, url: str, dest: Path, *, sha256: str | None = None, token: str | None = None, what: str = "file") -> Path:
        """Download to ``dest`` through a temp file; verify before the file is published."""
        _require_https(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(dest.parent), prefix=f".{dest.name}.", suffix=".part")
        tmp_path = Path(tmp)
        try:
            with self._open(url, token) as response, open(fd, "wb") as out:
                shutil.copyfileobj(response, out, length=1024 * 1024)
            if sha256:
                verify_sha256(tmp_path, sha256, what=what)
            tmp_path.replace(dest)
            return dest
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise

    def text(self, url: str, *, token: str | None = None) -> str:
        _require_https(url)
        with self._open(url, token) as response:
            return response.read().decode("utf-8")
