"""Thin wrapper over Cloudflare Workers AI (REST): image generation and model search.

Smoke-test findings (25 Nov 2026) that shaped this file:
  - FLUX.1 schnell accepts ONLY `prompt` and `steps` (max 8). No seed, no size:
    its images cannot be reproduced by seed.
  - FLUX.2 klein (4B / 9B) takes a multipart form: prompt, width, height, seed,
    and up to 4 reference images (input_image_0..3). Steps are fixed at 4.
  - klein-4b is Apache 2.0; klein-9b is non-commercial, so 4B is the default.
"""
from __future__ import annotations

import base64
import math
from dataclasses import dataclass
from typing import Any

import httpx

API = "https://api.cloudflare.com/client/v4/accounts/{account}/ai"


@dataclass(frozen=True)
class ImageModel:
    form: str  # "json" or "multipart"
    seed: bool
    size: bool
    steps: bool
    max_refs: int


MODELS: dict[str, ImageModel] = {
    "@cf/black-forest-labs/flux-1-schnell": ImageModel("json", seed=False, size=False, steps=True, max_refs=0),
    "@cf/black-forest-labs/flux-2-klein-4b": ImageModel("multipart", seed=True, size=True, steps=False, max_refs=4),
    "@cf/black-forest-labs/flux-2-klein-9b": ImageModel("multipart", seed=True, size=True, steps=False, max_refs=4),
}

# Published Workers AI price for FLUX.1 schnell: 4.80 neurons per 512x512 tile + 9.60 per step.
# Free tier: 10,000 neurons/day. klein pricing is filled in from the pricing page in COSTS.md.
_NEURONS = {"@cf/black-forest-labs/flux-1-schnell": (4.80, 9.60)}


def estimate_neurons(model: str, width: int, height: int, steps: int) -> float | None:
    if model not in _NEURONS:
        return None
    per_tile, per_step = _NEURONS[model]
    tiles = math.ceil(width / 512) * math.ceil(height / 512)
    return round(per_tile * tiles + per_step * steps, 2)


def _raise_with_body(r: httpx.Response) -> None:
    """Like raise_for_status, but keeps Cloudflare's explanation (it lives in the body)."""
    if r.is_error:
        raise httpx.HTTPStatusError(
            f"HTTP {r.status_code} from {r.request.url.path}: {r.text[:400]}",
            request=r.request,
            response=r,
        )


class Cloudflare:
    def __init__(self, account_id: str, token: str, client: httpx.Client | None = None, timeout: float = 180):
        self.base = API.format(account=account_id)
        self.http = client or httpx.Client(timeout=timeout)
        self.headers = {"Authorization": f"Bearer {token}"}

    def search_models(self, query: str) -> list[dict[str, Any]]:
        r = self.http.get(f"{self.base}/models/search", params={"search": query}, headers=self.headers)
        _raise_with_body(r)
        return [
            {"name": m.get("name"), "task": (m.get("task") or {}).get("name"),
             "description": (m.get("description") or "")[:160]}
            for m in r.json().get("result", [])
        ]

    def image(
        self,
        model: str,
        prompt: str,
        *,
        seed: int | None = None,
        steps: int | None = None,
        width: int | None = None,
        height: int | None = None,
        refs: list[bytes] | None = None,
    ) -> bytes:
        spec = MODELS.get(model)
        if spec is None:
            raise ValueError(f"Unknown image model {model!r}; add it to MODELS with its capabilities")
        refs = refs or []
        unsupported = [name for name, given, ok in (
            ("seed", seed is not None, spec.seed),
            ("size", width is not None or height is not None, spec.size),
            ("steps", steps is not None, spec.steps),
        ) if given and not ok]
        if unsupported:
            raise ValueError(f"{model} does not accept {unsupported}")
        if len(refs) > spec.max_refs:
            raise ValueError(f"{model} accepts at most {spec.max_refs} reference images, got {len(refs)}")

        url = f"{self.base}/run/{model}"
        if spec.form == "json":
            payload: dict[str, Any] = {"prompt": prompt}
            if steps is not None:
                payload["steps"] = steps
            r = self.http.post(url, json=payload, headers=self.headers)
        else:
            fields: dict[str, Any] = {"prompt": (None, prompt)}
            if seed is not None:
                fields["seed"] = (None, str(seed))
            if width and height:
                fields["width"], fields["height"] = (None, str(width)), (None, str(height))
            for i, data in enumerate(refs):
                fields[f"input_image_{i}"] = (f"ref{i}.png", data, "image/png")
            r = self.http.post(url, files=fields, headers=self.headers)

        _raise_with_body(r)
        if r.headers.get("content-type", "").startswith("image/"):
            return r.content
        body = r.json()
        if not body.get("success", True):
            raise RuntimeError(f"Cloudflare error: {body.get('errors')}")
        image_b64 = (body.get("result") or {}).get("image")
        if not image_b64:
            raise RuntimeError("Cloudflare returned no image")
        return base64.b64decode(image_b64)
