# Dockly Library

The official application catalog for [Dockly](https://github.com/buadamlaz/Dockly) — a self-hosted Docker management platform.

This repo is metadata only: no image binaries, nothing built here. `index.json` at the root is the catalog Dockly fetches; each entry points at `apps/<app-id>/`, containing:

- `app.yaml` — the manifest (name, description, image(s), ports, volumes, environment, security posture), validated against `schema/app.schema.json`
- `docker-compose.yml` — reference only, for humans comparing against the upstream deployment method; Dockly's installer reads `app.yaml` directly, never this file
- `icon.svg` + `icon.png` — this app's own icon, living in this repo (not a third-party icon pack); `app.yaml`'s `icon` field is the full jsDelivr CDN URL to the `.svg` (`cdn.jsdelivr.net/gh/buadamlaz/dockly-library@main/apps/<app-id>/icon.svg`)
- `screenshots/` — optional PNG/JPG/WebP files, filenames listed in `app.yaml`

An app is either single-container (`images: [...]`) or a multi-container stack (`services: [...]`, e.g. an app plus its own database) — the schema's `oneOf` enforces exactly one shape.

## Contributing an app

1. Copy an existing folder under `apps/` as a starting point.
2. Fill in `app.yaml` against `schema/app.schema.json`.
3. Add the entry to `index.json`.
4. Open a PR — CI validates schema conformance, cross-checks `index.json`, and parses the compose file. `privileged`/`host_network`/`host_pid`/`host_ipc`/`docker_socket: true` gets flagged for maintainer review, not auto-blocked.

`index.json`'s `maintenance` object can take the catalog offline client-side (`enabled: true`, optional `until` — must include a UTC offset — and per-locale `message`) without touching any app data.

## Trust labels

Every entry distinguishes "Maintained by: `<upstream project>`" from "Catalog entry maintained by: Dockly Community" — this repo never claims to be the developer of what it catalogs.

## Non-goals

No image builds, no image hosting, no guarantee of security/quality/legality for cataloged apps. Review what you install.

Full protocol spec: [`docs/LIBRARY_PROTOCOL.md`](https://github.com/buadamlaz/Dockly/blob/main/docs/LIBRARY_PROTOCOL.md) in the main Dockly repo.
