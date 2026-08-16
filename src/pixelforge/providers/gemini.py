"""Google Gemini image generation.

UNVERIFIED AGAINST A LIVE KEY. This was written without API access, so the
endpoint and response shape are the documented ones rather than ones observed
working. The model id and base URL are both configurable precisely because they
are the parts most likely to have moved -- if a call fails, change
``[generate] model`` in pixelforge.toml before changing this file.

Standard library only: one HTTP POST does not justify a dependency.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import urllib.error
import urllib.request
from pathlib import Path

from .base import GenerationError, Provider, ProviderResult

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class Gemini(Provider):
    api_key_env = "GEMINI_API_KEY"

    def __init__(self, model: str = "gemini-2.5-flash-image",
                 api_key: str | None = None, timeout: int = 120,
                 base_url: str = BASE_URL) -> None:
        super().__init__(model, api_key or os.environ.get(self.api_key_env), timeout)
        self.base_url = base_url.rstrip("/")

    def generate(self, prompt: str, reference: Path | None = None,
                 count: int = 1) -> ProviderResult:
        if not self.api_key:
            raise GenerationError(
                "no API key: set %s in the environment, or pass --api-key"
                % self.api_key_env
            )

        parts: list[dict] = [{"text": prompt}]
        if reference is not None:
            parts.append(self._inline(Path(reference)))

        body = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE"],
                                 "candidateCount": max(1, count)},
        }

        payload = self._post("%s/models/%s:generateContent" % (self.base_url, self.model), body)
        return self._read(payload)

    # ------------------------------------------------------------------ internals

    @staticmethod
    def _inline(path: Path) -> dict:
        if not path.exists():
            raise GenerationError("no reference image at %s" % path)
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        return {"inline_data": {"mime_type": mime,
                                "data": base64.b64encode(path.read_bytes()).decode("ascii")}}

    def _post(self, url: str, body: dict) -> dict:
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as failure:
            detail = failure.read().decode("utf-8", "replace")[:800]
            raise GenerationError(
                "%s returned HTTP %d\n%s" % (self.model, failure.code, detail)
            ) from failure
        except urllib.error.URLError as failure:
            raise GenerationError("could not reach %s: %s" % (url, failure.reason)) from failure
        except json.JSONDecodeError as failure:
            raise GenerationError("%s returned a non-JSON body" % self.model) from failure

    def _read(self, payload: dict) -> ProviderResult:
        if "error" in payload:
            error = payload["error"]
            raise GenerationError("%s: %s" % (error.get("status", "error"),
                                              error.get("message", "unknown")))

        images: list[bytes] = []
        mimes: list[str] = []
        notes: list[str] = []
        for candidate in payload.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                # The API has used both spellings; accept either rather than
                # breaking on a rename that does not change the meaning.
                blob = part.get("inlineData") or part.get("inline_data")
                if blob and blob.get("data"):
                    images.append(base64.b64decode(blob["data"]))
                    mimes.append(blob.get("mimeType") or blob.get("mime_type") or "image/png")
                elif part.get("text"):
                    notes.append(part["text"])

        if not images:
            reason = "; ".join(notes) if notes else json.dumps(payload)[:600]
            raise GenerationError(
                "%s returned no image. Response said: %s" % (self.model, reason)
            )
        return ProviderResult(images, mimes, "\n".join(notes), self.model)
