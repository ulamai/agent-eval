from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _sha256_bytes(value: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(value)
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def collect_file_hashes(run_dir: str | Path) -> dict[str, str]:
    base = Path(run_dir)
    if not base.exists():
        raise FileNotFoundError(f"run directory not found: {base}")

    hashes: dict[str, str] = {}
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(base).as_posix()
        if rel == "manifest.json":
            continue
        if rel.startswith("run/provenance_attestation"):
            continue
        hashes[rel] = _sha256_file(path)
    return hashes


def build_attestation(
    run_dir: str | Path,
    *,
    secret: str | None = None,
    signer: str = "local",
) -> dict[str, Any]:
    base = Path(run_dir)
    manifest_path = base / "manifest.json"
    manifest = {}
    if manifest_path.exists():
        with manifest_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            manifest = payload

    file_hashes = collect_file_hashes(base)
    attestation_payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "run_id": manifest.get("run_id"),
        "dataset_id": manifest.get("dataset_id"),
        "signer": signer,
        "hash_algorithm": "sha256",
        "file_hashes": file_hashes,
        "manifest_sha256": _sha256_file(manifest_path) if manifest_path.exists() else None,
    }

    signature = None
    signature_algorithm = None
    if secret:
        signature = hmac.new(
            secret.encode("utf-8"),
            _canonical_json(attestation_payload),
            hashlib.sha256,
        ).hexdigest()
        signature_algorithm = "hmac-sha256"

    return {
        **attestation_payload,
        "signature": signature,
        "signature_algorithm": signature_algorithm,
    }


def write_attestation(
    run_dir: str | Path,
    *,
    out_path: str | Path | None = None,
    secret: str | None = None,
    signer: str = "local",
) -> Path:
    base = Path(run_dir)
    attestation = build_attestation(base, secret=secret, signer=signer)
    target = (
        Path(out_path)
        if out_path is not None
        else base / "run" / "provenance_attestation.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(attestation, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return target


def verify_attestation(
    run_dir: str | Path,
    *,
    attestation_path: str | Path | None = None,
    secret: str | None = None,
) -> dict[str, Any]:
    base = Path(run_dir)
    source = (
        Path(attestation_path)
        if attestation_path is not None
        else base / "run" / "provenance_attestation.json"
    )
    if not source.exists():
        raise FileNotFoundError(f"attestation file not found: {source}")

    with source.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("attestation payload must be an object")

    recorded_hashes = payload.get("file_hashes", {})
    if not isinstance(recorded_hashes, dict):
        recorded_hashes = {}
    current_hashes = collect_file_hashes(base)

    hash_mismatches: list[dict[str, Any]] = []
    for rel in sorted(set(recorded_hashes) | set(current_hashes)):
        recorded = recorded_hashes.get(rel)
        current = current_hashes.get(rel)
        if recorded != current:
            hash_mismatches.append(
                {"path": rel, "recorded": recorded, "current": current}
            )

    signature_valid = None
    signature_error = None
    signature = payload.get("signature")
    if signature is not None:
        if not secret:
            signature_valid = False
            signature_error = "secret required to verify signature"
        else:
            to_verify = dict(payload)
            to_verify.pop("signature", None)
            to_verify.pop("signature_algorithm", None)
            expected = hmac.new(
                secret.encode("utf-8"),
                _canonical_json(to_verify),
                hashlib.sha256,
            ).hexdigest()
            signature_valid = hmac.compare_digest(str(signature), expected)
            if not signature_valid:
                signature_error = "signature mismatch"

    passed = not hash_mismatches and (signature_valid in (None, True))
    return {
        "passed": passed,
        "run_dir": str(base),
        "attestation_path": str(source),
        "hash_mismatches": hash_mismatches,
        "signature_valid": signature_valid,
        "signature_error": signature_error,
    }


def apply_manifest_hashes(run_dir: str | Path) -> Path:
    base = Path(run_dir)
    manifest_path = base / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")

    with manifest_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, dict):
        raise ValueError("manifest payload must be an object")

    manifest["file_hashes"] = collect_file_hashes(base)
    with manifest_path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return manifest_path
