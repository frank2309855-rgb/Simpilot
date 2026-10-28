# Security scope

This is a **single-user, trusted local research tool**, not a hosted service or a security isolation boundary. Do not bind it to a public address, add port forwarding, use an untrusted tunnel, or run it with administrator privileges.

## Included protections

- Listener fixed to 127.0.0.1; expected Host names/port checked.
- Cross-site Fetch Metadata and foreign Origin rejected (the OAuth redirect is a separately state/PKCE-validated exception).
- API reads/actions require a random per-process header token. Reports/downloads require the session token or an HttpOnly, SameSite=Strict session cookie issued when opening the local page.
- No cross-origin sharing headers, remote front-end assets or HTTP file-upload/extraction endpoints.
- Fixed Python helper commands use argument arrays and the active interpreter, not a shell built from user input.
- Report file reads are contained inside the selected run and accept only HTML/JSON/CSV. Run deletion uses a validated direct-child ID, preview fingerprint and explicit confirmation; redirected paths are rejected.
- Models are validated JSON and reconstructed with frozen parameters. No pickle or joblib load is used. NumPy caches use allow_pickle=False.
- Drive endpoints are fixed Google HTTPS URLs; OAuth uses state and PKCE, TLS validation is retained, and tokens stay in process memory.

## Residual limits

A user who intentionally chooses a local path grants the process access under that user's filesystem permissions. The API is not a general-purpose sandbox; it can inspect local files and process supplied data. The CLI can write into the chosen output workspace. Other malicious local programs/extensions or compromised project code are outside the protection of a localhost token. JSON/CSV/model input can consume computation or memory despite input limits.

The static page needs a bootstrap session token, and the app/report currently permit inline scripts/styles in CSP. Existing same-origin XSS protections depend on output escaping and keeping input/rendering code trustworthy; CSP is not a complete XSS defense. Keep report and project files trusted.

No real Google account, filesystem ACLs, browser-extension state or machine firewall has been audited by this package. drive.readonly can read all files the account may access, not just five folders. User-generated outputs can contain source paths, notes and file identities; never assume they are automatically safe to publish.

## Publish safely

Publish only the explicit release contents in RELEASE_FILES.json, using a new repository history. Do not copy the private research checkout, .git, credentials, project exports, runtime outputs, caches, trained models or old logs. Use `.gitignore` as a second layer, not the sole control. Before each upload run the included local scan and inspect the file list. The scanner is a targeted leak check, not a guarantee of complete secret detection.

If a real secret has been committed or shared, removing it from the current file is insufficient: revoke/rotate it and inspect repository history. The provided package starts without Git history; no private history has been imported.


### Curated public benchmark

`benchmarks/five_recipe_low_q/` is an explicit exception for reviewed scientific-field exports. This does not authorize uploading generated `runtime/` folders, complete training audits, original reports or trained models. Newly generated outputs still need a separate privacy review.
