# Third-party components

- cc-connect upstream: https://github.com/chenhg5/cc-connect
- Pinned upstream commit: `5d4c96dd12774574369e75b60084140101c9a59a` (v1.4.1).
- The pinned upstream README and npm package metadata identify its license as MIT. This package provides a patch against that source; the installer downloads the pinned upstream archive. Preserve upstream notices and verify applicable license files when distributing derived binaries or source.
- Console patch: shell-free argv commands, platform-independent authenticated routing, complete reply delivery, and loopback defaults for optional management/bridge listeners. The patch is not an official upstream release.
- Python dependencies are pinned in `mobile-ui/requirements.lock`; frontend dependencies are pinned in `mobile-ui/frontend/package-lock.json`; cc-connect dependencies remain governed by its upstream `go.mod`/`go.sum`.
- Caddy, Go, Python, Node.js, the Codex CLI and desktop client are installed separately. Their executable binaries and user login state are not redistributed in this archive.
- The project author's own source license has not yet been selected. This document does not grant additional rights in third-party software or select a license on the author's behalf.

Full notices for bundled React, React DOM, Scheduler and Lucide code: [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md). Versions were checked against the lockfile.
