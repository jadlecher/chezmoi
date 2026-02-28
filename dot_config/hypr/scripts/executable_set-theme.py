#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
import time
from os import listdir
from os.path import isfile, join
from pathlib import Path

import yaml

extension = ".conf"
themes = ["light", "dark"]


def get_system_theme():
    command = ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"]
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, check=True, text=True)
        value = result.stdout.strip().strip("'")
        prefix = "prefer-"
        if value.startswith(prefix):
            theme = value.removeprefix(prefix)
            if theme in themes:
                return theme
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    # Keep theming functional on minimal/non-GNOME sessions.
    return "dark"


def list_config_files(path: str):
    return [
        file
        for file in listdir(path)
        if file.endswith(extension) and isfile(join(path, file))
    ]


def get_opposite_theme(theme: str):
    return [x for x in themes if x != theme][0]


def filter_inapplicable_config_files(theme: str, files: list[str]):
    pattern = f"^.*-{get_opposite_theme(theme)}\\.conf$"
    return [file for file in files if not re.search(pattern, file, re.IGNORECASE)]


def sync_link(src: str, dest: str):
    src = os.path.abspath(src)
    dest = os.path.abspath(dest)
    exists = False
    if os.path.exists(dest):
        if os.path.islink(dest) and os.path.abspath(os.readlink(dest)) == src:
            exists = True
        else:
            os.remove(dest)
    if not exists:
        os.symlink(src, dest)


def sync_dir(input_dir: str, output_dir: str, files: list[str]):
    os.makedirs(output_dir, exist_ok=True)
    for file in files:
        src = os.path.join(input_dir, file)
        dest = os.path.join(output_dir, file)
        sync_link(src, dest)

    # remove stale links
    for file in listdir(output_dir):
        path = os.path.join(output_dir, file)
        if os.path.islink(path) and file.endswith(extension) and file not in files:
            os.remove(path)


def get_outputs() -> list[dict]:
    commands = (["hyprctl", "monitors", "-j"], ["wlr-randr", "--json"])
    for command in commands:
        try:
            process = subprocess.check_output(command, text=True)
            return json.loads(process)
        except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
            continue
    raise RuntimeError("unable to query outputs with hyprctl or wlr-randr")


def start_wallpaper_daemon():
    command = ["swww-daemon", "--no-cache"]
    if subprocess.run(["pidof", command[0]], stdout=subprocess.DEVNULL).returncode != 0:
        print(f"Starting {command[0]}")
        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        timeout = 10  # seconds
        start = time.time()
        end = start
        while (
            end - start < timeout
            and subprocess.run(
                ["swww", "clear"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            ).returncode
            != 0
        ):
            end = time.time()
        if end - start >= timeout:
            raise RuntimeError(f"Timed out while starting {command[0]}")


def set_wallpaper(output: str, path: str):
    process = subprocess.run(
        [
            "swww",
            "img",
            "--transition-type",
            "fade",
            "--transition-step",
            "2",
            "--transition-fps",
            "120",
            "--outputs",
            output,
            path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if process.returncode != 0:
        error = (process.stderr or process.stdout or "unknown error").strip()
        print(f"warning: failed to set wallpaper on {output}: {error}")
    return process.returncode == 0


def resolve_wallpaper_path(
    wallpaper: str,
    theme: str,
    resolver: str,
    catalog: str,
    local_catalog: str,
    fetch_policy: str,
) -> str | None:
    # Treat values that look like file paths as literal paths for migration compatibility.
    if "/" in wallpaper or wallpaper.startswith(".") or wallpaper.startswith("~"):
        path = os.path.abspath(os.path.expanduser(wallpaper))
        if os.path.isfile(path):
            return path
        print(f"warning: wallpaper path not found: {path}")
        return None

    command = [
        resolver,
        "--asset",
        wallpaper,
        "--variant",
        theme,
        "--fetch",
        fetch_policy,
        "--catalog",
        catalog,
        "--local-catalog",
        local_catalog,
    ]
    process = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if process.returncode == 0:
        return process.stdout.strip()
    if process.stderr:
        print(process.stderr.strip())
    else:
        print(f"warning: failed to resolve wallpaper asset: {wallpaper}")
    return None


def get_output(outputs: list[dict], desc: str) -> str | None:
    for output in outputs:
        name = output["name"]
        description = output.get("description", "")
        if description == desc:
            return name
        matches = re.compile(f"(.+) \\({name}\\)$").search(description)
        if matches is not None:
            if desc == matches.group(1):
                return name
    return None


def apply_wallpaper_config(
    theme: str,
    config: str,
    resolver: str,
    catalog: str,
    local_catalog: str,
    fetch_policy: str,
) -> int:
    outputs = get_outputs()
    applied = 0
    desc_pattern = re.compile("^desc:(.+)")
    with open(config, "r") as file:
        for display, options in yaml.safe_load(file).items():
            output = display
            matches = desc_pattern.search(output)
            if matches is not None:
                desc = matches.group(1)
                output = get_output(outputs, desc)
            if theme in options and output is not None:
                wallpaper = resolve_wallpaper_path(
                    options[theme],
                    theme,
                    resolver,
                    catalog,
                    local_catalog,
                    fetch_policy,
                )
                if wallpaper is not None and set_wallpaper(output, wallpaper):
                    applied += 1
    return applied


def restore_wallpapers(
    theme: str,
    config: str,
    retries: int,
    retry_delay: float,
    resolver: str,
    catalog: str,
    local_catalog: str,
    fetch_policy: str,
) -> bool:
    start_wallpaper_daemon()
    for attempt in range(retries):
        try:
            if (
                apply_wallpaper_config(
                    theme,
                    config,
                    resolver,
                    catalog,
                    local_catalog,
                    fetch_policy,
                )
                > 0
            ):
                return True
        except (RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError, KeyError):
            pass
        if attempt + 1 < retries:
            time.sleep(retry_delay)
    print("warning: failed to apply wallpapers to any output")
    return False


parser = argparse.ArgumentParser(prog="set-theme")
parser.add_argument(
    "-i",
    "--input-dir",
    help="A directory containing the input configuration files",
)
parser.add_argument(
    "-o",
    "--output-dir",
    help="A directory containing the output configuration files",
)
parser.add_argument("-w", "--wallpaper-config", help="The wallpaper configuration file")
parser.add_argument(
    "--wallpaper-only",
    action="store_true",
    help="Only apply wallpapers and skip config symlink updates",
)
parser.add_argument(
    "--wallpaper-retries",
    type=int,
    default=1,
    help="Number of attempts to apply wallpapers",
)
parser.add_argument(
    "--wallpaper-retry-delay",
    type=float,
    default=0.2,
    help="Delay in seconds between wallpaper apply attempts",
)
parser.add_argument(
    "--image-resolver",
    default="~/.config/media/scripts/image-resolve.py",
    help="Path to image resolver command",
)
parser.add_argument(
    "--image-catalog",
    default="~/.config/media/image-catalog.yaml",
    help="Path to shared image catalog",
)
parser.add_argument(
    "--image-local-catalog",
    default="~/.config/media/image-catalog.local.yaml",
    help="Path to local image catalog override",
)
parser.add_argument(
    "--image-fetch-policy",
    choices=["never", "missing"],
    default="never",
    help="Whether to fetch missing remote images while resolving assets",
)
parser.add_argument(
    "--require-wallpaper",
    action="store_true",
    help="Exit with failure if no wallpapers could be applied",
)
args = parser.parse_args()

resolver = str(Path(args.image_resolver).expanduser())
catalog = str(Path(args.image_catalog).expanduser())
local_catalog = str(Path(args.image_local_catalog).expanduser())

theme = get_system_theme()
if not args.wallpaper_only:
    if not args.input_dir or not args.output_dir:
        parser.error("--input-dir and --output-dir are required unless --wallpaper-only is set")
    files = list_config_files(args.input_dir)
    files = filter_inapplicable_config_files(theme, files)
    input_dir = os.path.abspath(args.input_dir)
    output_dir = os.path.abspath(args.output_dir)
    sync_dir(input_dir, output_dir, files)

if args.wallpaper_config:
    applied = restore_wallpapers(
        theme,
        args.wallpaper_config,
        max(1, args.wallpaper_retries),
        max(0.0, args.wallpaper_retry_delay),
        resolver,
        catalog,
        local_catalog,
        args.image_fetch_policy,
    )
    if args.require_wallpaper and not applied:
        raise RuntimeError("no wallpapers were applied")
elif args.wallpaper_only:
    parser.error("--wallpaper-config is required with --wallpaper-only")
