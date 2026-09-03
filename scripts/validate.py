#!/usr/bin/env python3
"""Validates every app manifest against schema/app.schema.json, checks that
index.json entries point at real, complete app folders, and flags (without
failing the build) any security-sensitive settings so a human reviewer sees
them on the PR — mirrors docs/LIBRARY_PROTOCOL.md §2 in the main Dockly repo.
"""
import datetime
import json
import pathlib
import sys

import yaml
from jsonschema import Draft7Validator

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schema" / "app.schema.json"
INDEX_PATH = ROOT / "index.json"
APPS_DIR = ROOT / "apps"

DANGEROUS_FLAGS = ["privileged", "host_network", "host_pid", "host_ipc", "docker_socket"]


def fail(msg: str) -> None:
    print(f"::error::{msg}")
    global had_error
    had_error = True


def warn(msg: str) -> None:
    print(f"::warning::{msg}")


def main() -> int:
    global had_error
    had_error = False

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft7Validator(schema)

    manifest_paths = sorted(APPS_DIR.glob("*/*/app.yaml"))
    if not manifest_paths:
        fail("No app.yaml manifests found under apps/.")

    seen_ids = set()
    multi_service_ids = set()
    manifest_by_id = {}
    for manifest_path in manifest_paths:
        app_dir = manifest_path.parent
        try:
            data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            fail(f"{manifest_path}: invalid YAML: {e}")
            continue

        errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
        for err in errors:
            loc = "/".join(str(p) for p in err.path) or "(root)"
            fail(f"{manifest_path}: {loc}: {err.message}")

        if errors:
            continue

        app_id = data["id"]
        if app_id in seen_ids:
            fail(f"{manifest_path}: duplicate app id '{app_id}'")
        seen_ids.add(app_id)
        manifest_by_id[app_id] = data

        # A manifest with a services[] list is a real, Dockly-supported
        # multi-container stack (internal/docker/stack.go in the main repo)
        # — its own compose.file is decorative reference only, never parsed
        # by Dockly's install pipeline, so it's irrelevant to whether this
        # app is installable.
        declares_stack = isinstance(data.get("services"), list) and len(data["services"]) > 0

        compose_file = app_dir / data["compose"]["file"]
        if not compose_file.exists():
            fail(f"{manifest_path}: compose.file '{data['compose']['file']}' does not exist")
        elif not declares_stack:
            # Single-service-shaped manifest (images[]) — if its OWN
            # reference compose file actually has more than one service,
            # that's a real mismatch: Dockly's compose importer only ever
            # imports the first service, so installing this would silently
            # create just one container, missing whatever else the app
            # actually depends on. Only relevant for the legacy images[]
            # shape; a services[]-based manifest is unaffected by this check.
            try:
                compose_doc = yaml.safe_load(compose_file.read_text(encoding="utf-8"))
                services = (compose_doc or {}).get("services", {})
                if isinstance(services, dict) and len(services) > 1:
                    multi_service_ids.add(app_id)
            except yaml.YAMLError as e:
                fail(f"{compose_file}: invalid YAML: {e}")

        security = data.get("security", {})
        flagged = [f for f in DANGEROUS_FLAGS if security.get(f) is True]
        if flagged:
            warn(f"{manifest_path}: security-sensitive settings enabled ({', '.join(flagged)}) — requires maintainer review before merge")

        # Every listed screenshot filename must actually exist in this app's
        # own screenshots/ folder — a typo here would otherwise ship a
        # broken <img> to every Dockly instance instead of failing the PR.
        for filename in data.get("screenshots", []):
            screenshot_path = app_dir / "screenshots" / filename
            if not screenshot_path.exists():
                fail(f"{manifest_path}: screenshots entry '{filename}' does not exist at {screenshot_path.relative_to(ROOT)}")

    # Cross-check index.json against what's actually on disk.
    if INDEX_PATH.exists():
        index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        index_ids = set()
        for entry in index.get("apps", []):
            entry_id = entry.get("id")
            index_ids.add(entry_id)
            app_path = ROOT / entry["path"]
            if not (app_path / "app.yaml").exists():
                fail(f"index.json: entry '{entry_id}' points at '{entry['path']}', which has no app.yaml")

            # Dockly's compose importer only imports a compose file's first
            # service — installing a multi-service app without this flag
            # would silently create just one container, missing whatever
            # else the app actually depends on (its own database, etc.).
            if entry_id in multi_service_ids and entry.get("installable", True):
                fail(f"index.json: '{entry_id}' has more than one compose service but is not marked \"installable\": false")

            # index.json's own "image" field lets Dockly show "Installed" on
            # the catalog grid without fetching every app.yaml — it must
            # stay in sync with the manifest's real image or that check
            # silently stops working for this one app (real bug fixed
            # 2026-08-30: this field didn't exist at all yet, so it could
            # only ever be checked on the detail page, not the grid).
            manifest = manifest_by_id.get(entry_id)
            if manifest and "image" in entry:
                if isinstance(manifest.get("services"), list) and manifest["services"]:
                    primary = next((s for s in manifest["services"] if s.get("primary")), manifest["services"][0])
                    actual_repo = primary.get("image", {}).get("repository")
                    source = f"its primary service ('{primary.get('name')}')'s image.repository"
                else:
                    actual_repo = manifest.get("images", [{}])[0].get("repository")
                    source = "its manifest's images[0].repository"
                if entry["image"] != actual_repo:
                    fail(f"index.json: '{entry_id}' image '{entry['image']}' does not match {source} '{actual_repo}'")

        missing_from_index = seen_ids - index_ids
        for app_id in missing_from_index:
            warn(f"'{app_id}' has a manifest but is not listed in index.json")

        maintenance = index.get("maintenance")
        if maintenance is not None:
            if not isinstance(maintenance.get("enabled"), bool):
                fail("index.json: maintenance.enabled must be a boolean")
            until = maintenance.get("until")
            if until is not None:
                if not isinstance(until, str):
                    fail("index.json: maintenance.until must be a string or null")
                else:
                    try:
                        # Require an explicit UTC offset, not a naive local
                        # time — Dockly converts this to each viewer's own
                        # timezone, which only works if the source time is
                        # unambiguous.
                        parsed = datetime.datetime.fromisoformat(until)
                        if parsed.tzinfo is None:
                            fail(f"index.json: maintenance.until '{until}' has no UTC offset (e.g. +03:00) — required so every viewer converts it correctly")
                    except ValueError:
                        fail(f"index.json: maintenance.until '{until}' is not a valid ISO 8601 timestamp")
    else:
        fail("index.json not found at repo root.")

    if had_error:
        print("\nValidation FAILED.")
        return 1

    print(f"Validation passed — {len(manifest_paths)} app manifest(s) checked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
