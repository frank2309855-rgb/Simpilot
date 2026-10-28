# Pre-publication security and privacy review — 2026-10-27

Scope: this explicit source/data release, its runtime dependencies, and the local HTTP platform. This is a code and reproducibility review, not a penetration test or an audit of the user's computer.

## Findings and changes

| Finding | Release treatment |
|---|---|
| Original manifests contain source paths and Google Drive identities | Rebuilt by a calculation-field allowlist. CSV bytes/checksums, q grids, direction counts, geometry and normalization retained; original source lists, transfer/cache details and private path fields omitted. |
| Original launcher assumes a personal Anaconda installation | Uses a project virtual environment or the caller's Python. No personal interpreter path is shipped. |
| Existing environment includes dependencies with public advisories | Pinned updated requests 2.34.2, urllib3 2.8.0 and idna 3.20; all runtime/transitive dependencies fixed and installed in a separate environment. Original scientific versions NumPy 2.3.5 / SciPy 1.16.3 / scikit-learn 1.7.2 retained. |
| Report/download GET routes did not require a session | Per-process session check via token or HttpOnly, SameSite=Strict, port-specific browser cookie. API actions continue to require their header token. |
| GET requests lacked an explicit cross-site guard | Foreign Origin and cross-site/same-site Fetch Metadata rejected. Google OAuth callback remains the intentional exception, protected by state, PKCE and expiry. |
| Report containment started at a resolved run path | Added a direct-parent check inside the resolved run root as well as file containment and extension checks. |
| Potential accidental publication of the research working tree | New release directory with explicit file hashes, no imported Git history, runtime ignore rules, scanner and ZIP allowlist. |

The earlier HTTP packages had published advisories; applicability depends on the vulnerable function and attack conditions. Finding an advisory does not establish exploitation on this computer. This work updates the portable environment only. Continue using the new isolated environment for the reviewed release; the original Anaconda environment has not been upgraded.

## Existing controls retained

Loopback-only bind; strict Host check; random API header token; no CORS sharing; output escaping; no arbitrary shell interpolation; fixed Google HTTPS endpoints/TLS; OAuth consent/state/PKCE; scoped run-deletion preview and confirmation; JSON model reconstruction; allow_pickle=False for derived caches; bounded CSV/raw/Drive processing. No model-loading web endpoint, HTTP upload/unzip endpoint, external-URL fetch proxy, or Drive write/delete operation was introduced.

## Dependency lookup

The release's 11 pinned runtime packages returned no advisory IDs from the OSV batch API on the review date. Primary maintainer references for identified older versions:

- [Requests GHSA-gc5v-m9x4-r6x2](https://github.com/psf/requests/security/advisories/GHSA-gc5v-m9x4-r6x2)
- [urllib3 maintainer advisories](https://github.com/urllib3/urllib3/security/advisories)
- [idna GHSA-65pc-fj4g-8rjx](https://github.com/kjd/idna/security/advisories/GHSA-65pc-fj4g-8rjx)

No research files, credentials or local paths were submitted in these lookups; only public package names/versions were queried. See [VALIDATION.md](VALIDATION.md) for actual checks and limits. Python itself, pip and operating-system security were not upgraded or exhaustively assessed.

## Residual risks and owner decisions

- Trusted-user local filesystem access is an intentional capability. This is not a multi-user or public service; do not expose it through tunnels or forwarding.
- CSP still allows the existing inline scripts/styles. Escaping and trusted code remain necessary; localhost tokens do not defend against a malicious local program or privileged browser extension.
- Newly generated local reports/audits can include absolute source paths, notes and, for Drive use, source identities. Runtime outputs are ignored, not automatically sanitized for sharing.
- Actual OAuth account permissions, disk ACLs, browser state and organizational policy remain unverified. Drive permission is account-wide read-only.
- Scientific and data-sharing limits remain: one seed per recipe, unconfirmed material/recipe mapping, and no validated stage-3 predictor. Licensing/collaboration approval must be confirmed before public GitHub publication.
- The local source tree had no `.git` directory at the inspected root, and no history was copied into this release. This is not an assertion that all other repositories or old shared copies are clean. Use new repository history; importing any old history requires a separate historical secret review.

No repository has been created/pushed, no Google account accessed, no credentials included, and no firewall/port-forwarding/protection setting changed.


## Documentation supplement - 2026-10-28

The public benchmark uses allowlisted scientific fields rather than a copied runtime folder. It includes already supplied targets, held-out predictions, metrics, fitted parameters, warnings, fingerprints and software versions. Source paths, Drive identities, accounts, original HTML reports, complete private audits and loadable models remain excluded.

Figures are static text-based SVG with Mermaid source. They contain no scripts, executable objects or external resource links. No service code, dependencies, network settings or access controls changed. Packaging/privacy review does not repeat or broaden earlier platform tests or the time-bound dependency lookup.
