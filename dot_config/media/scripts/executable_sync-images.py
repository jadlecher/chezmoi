#!/usr/bin/env python3
import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

import yaml


def load_yaml(path: str, required: bool) -> dict:
    file = Path(path).expanduser()
    if not file.exists():
        if required:
            raise FileNotFoundError(f"catalog not found: {file}")
        return {}
    with file.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"invalid yaml document: {file}")
    return data


def deep_merge(base: dict, overlay: dict) -> dict:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def valid_cached_file(path: Path, expected_sha256: str | None) -> bool:
    if not path.is_file():
        return False
    if not expected_sha256:
        return True
    return hash_file(path) == expected_sha256


def download(url: str, destination: Path):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, dir=destination.parent) as tmp:
        tmp_path = Path(tmp.name)
    try:
        with urllib.request.urlopen(url, timeout=30) as response, tmp_path.open("wb") as out:
            shutil.copyfileobj(response, out)
        tmp_path.replace(destination)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def normalize_path(path: str) -> Path:
    return Path(os.path.expandvars(path)).expanduser().resolve()


def parse_args():
    parser = argparse.ArgumentParser(prog="sync-images")
    parser.add_argument("--asset", help="Sync only one asset ID")
    parser.add_argument("--variant", choices=["light", "dark"], help="Sync only one variant")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when any remote source fails")
    parser.add_argument(
        "--catalog",
        default="~/.config/media/image-catalog.yaml",
        help="Path to the shared image catalog",
    )
    parser.add_argument(
        "--local-catalog",
        default="~/.config/media/image-catalog.local.yaml",
        help="Path to optional local catalog override",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        catalog = load_yaml(args.catalog, required=True)
        local_catalog = load_yaml(args.local_catalog, required=False)
        merged = deep_merge(catalog, local_catalog)
    except (FileNotFoundError, ValueError, yaml.YAMLError) as error:
        print(error, file=sys.stderr)
        return 2

    cache_dir = normalize_path(merged.get("cache_dir", "~/.local/share/theme-images"))
    assets = merged.get("assets") or {}
    if not isinstance(assets, dict):
        print("invalid assets map in catalog", file=sys.stderr)
        return 2

    total = 0
    cached = 0
    downloaded = 0
    failed = 0

    for asset_id, entry in assets.items():
        if args.asset and asset_id != args.asset:
            continue
        variants = (entry or {}).get("variants") or {}
        for variant, variant_entry in variants.items():
            if args.variant and variant != args.variant:
                continue
            sources = (variant_entry or {}).get("sources") or []
            for source in sources:
                if not isinstance(source, dict) or source.get("kind") != "remote":
                    continue
                total += 1
                filename = source.get("filename")
                url = source.get("url")
                expected_sha256 = source.get("sha256")
                if not filename or not url or not expected_sha256:
                    failed += 1
                    print(
                        f"failed: {asset_id}/{variant} missing filename/url/sha256 for remote source",
                        file=sys.stderr,
                    )
                    continue

                target = (cache_dir / filename).resolve()
                if valid_cached_file(target, expected_sha256):
                    cached += 1
                    print(f"cached: {asset_id}/{variant} -> {target}")
                    continue

                try:
                    download(url, target)
                except urllib.error.URLError as error:
                    failed += 1
                    print(f"failed: {asset_id}/{variant} download {url}: {error}", file=sys.stderr)
                    continue

                if not valid_cached_file(target, expected_sha256):
                    failed += 1
                    target.unlink(missing_ok=True)
                    print(f"failed: {asset_id}/{variant} checksum mismatch for {url}", file=sys.stderr)
                    continue

                downloaded += 1
                print(f"downloaded: {asset_id}/{variant} -> {target}")

    print(
        f"summary: remote_sources={total} cached={cached} downloaded={downloaded} failed={failed}"
    )
    if failed > 0 and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
