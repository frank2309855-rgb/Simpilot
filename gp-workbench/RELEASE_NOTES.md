# Release-only changes

Base: latest local source after the target-navigation and interface simplification updates. All three engine packages, static files and 13 existing CLI entry points are retained.

Added: five sanitized CSV/manifest pairs; relative example projects; example loader/API/button; no-browser runner; portable launchers and separate default runtime workspace; pinned runtime environment; minimal public tests and upload scan; English and Traditional Chinese documentation; explicit data/licensing status.

Security changes: cross-site GET checks, session-guarded report reads/downloads, port-scoped HttpOnly/SameSite cookie, direct-child report-root containment, and updated HTTP/IDNA dependencies. These affect the release copy; the research working copy and its environment were not modified.

No original trajectories, private source records, cached frame arrays, existing models/reports, credentials, personal project exports or Git history are included. Published SHA256 fingerprints support integrity, not proof of ownership or a data license. RELEASE_FILES.json lists all shipped files except itself; its own hash is intentionally not recursive. The ZIP has a separate SHA256 checksum file.


## Documentation and benchmark supplement - 2026-10-28

New folder: `gp-workbench-20261028`. The original 2026-10-27 folder and ZIP are unchanged.

Added static SVG architecture with editable Mermaid source, MODEL_CARD.md, BENCHMARK.md, two result figures, and allowlisted numerical benchmark CSV/JSON. README and the Traditional Chinese quick start link to the additions.

Existing 2026-10-27 numerical results were reused. Recorded scientific implementation hashes match the unchanged model engine. Original private runtime folders, HTML reports and loadable trained models were not copied. Warnings and interpolation/extrapolation scopes are preserved.

No runtime source, dependency, extraction rule, model setting or application test was changed or rerun for this supplement. The public manifest and ZIP checksum were regenerated.
