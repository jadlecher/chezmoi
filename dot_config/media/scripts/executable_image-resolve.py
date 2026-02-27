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

EXIT_INVALID_INPUT = 2
EXIT_NOT_FOUND = 4


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


def normalize_local_path(path: str) -> Path:
    return Path(os.path.expandvars(path)).expanduser().resolve()


def resolve_literal_path(path: str) -> Path | None:
    candidate = normalize_local_path(path)
    return candidate if candidate.is_file() else None


def resolve_remote_source(source: dict, cache_dir: Path, fetch_missing: bool) -> Path | None:
    filename = source.get("filename")
    url = source.get("url")
    expected_sha256 = source.get("sha256")

    if not filename or not url:
        return None

    target = (cache_dir / filename).resolve()
    if valid_cached_file(target, expected_sha256):
        return target

    if not fetch_missing:
        return None

    if not expected_sha256:
        print(
            f"warning: remote source requires sha256 for fetch: {url}",
            file=sys.stderr,
        )
        return None

    try:
        download(url, target)
    except urllib.error.URLError as error:
        print(f"warning: download failed for {url}: {error}", file=sys.stderr)
        return None

    if not valid_cached_file(target, expected_sha256):
        print(f"warning: checksum mismatch for {url}", file=sys.stderr)
        target.unlink(missing_ok=True)
        return None

    return target


def resolve_asset(catalog: dict, asset: str, variant: str, fetch_missing: bool) -> Path | None:
    assets = catalog.get("assets") or {}
    entry = assets.get(asset)
    if not isinstance(entry, dict):
        print(f"warning: unknown asset id: {asset}", file=sys.stderr)
        return None

    variants = entry.get("variants") or {}
    variant_entry = variants.get(variant)
    if not isinstance(variant_entry, dict):
        print(f"warning: asset {asset} does not define variant {variant}", file=sys.stderr)
        return None

    sources = variant_entry.get("sources") or []
    if not isinstance(sources, list):
        print(f"warning: invalid source list for {asset}/{variant}", file=sys.stderr)
        return None

    raw_cache_dir = catalog.get("cache_dir", "~/.local/share/theme-images")
    cache_dir = normalize_local_path(raw_cache_dir)

    for source in sources:
        if not isinstance(source, dict):
            continue
        kind = source.get("kind")
        if kind == "local":
            path = source.get("path")
            if path:
                resolved = resolve_literal_path(path)
                if resolved:
                    return resolved
        elif kind == "remote":
            resolved = resolve_remote_source(source, cache_dir, fetch_missing)
            if resolved:
                return resolved

    return None


def parse_args():
    parser = argparse.ArgumentParser(prog="image-resolve")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--asset", help="Asset ID from the shared image catalog")
    target.add_argument("--path", help="Literal file path")
    parser.add_argument(
        "--variant",
        choices=["light", "dark"],
        help="Theme variant; required with --asset",
    )
    parser.add_argument(
        "--fetch",
        choices=["never", "missing"],
        default="never",
        help="Whether to fetch missing remote files",
    )
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
        merged_catalog = deep_merge(catalog, local_catalog)

        if args.path:
            resolved = resolve_literal_path(args.path)
            if resolved:
                print(resolved)
                return 0
            print(f"warning: path not found: {args.path}", file=sys.stderr)
            return EXIT_NOT_FOUND

        if not args.variant:
            print("--variant is required with --asset", file=sys.stderr)
            return EXIT_INVALID_INPUT

        resolved = resolve_asset(
            merged_catalog,
            args.asset,
            args.variant,
            args.fetch == "missing",
        )
        if resolved:
            print(resolved)
            return 0
        return EXIT_NOT_FOUND
    except (FileNotFoundError, ValueError, yaml.YAMLError) as error:
        print(error, file=sys.stderr)
        return EXIT_INVALID_INPUT


if __name__ == "__main__":
    raise SystemExit(main())
