# Security

## Scope and threat model

This skill runs on the user's own machine. It writes geometry files and runs a
short-lived local preview server. The things that could go wrong:

1. **Physical harm through a printer.** A tool that drives a printer can start
   a job unattended or with wrong temperatures.
2. **Untrusted input files.** STL files, images, PDFs or web pages the user
   supplies may be malformed, huge, or carry text aimed at the assistant
   (prompt injection) in names, headers or comments.
3. **Path tricks.** A part name or output folder such as `../../.ssh/x` could
   write outside the project.
4. **The local preview server.** Other web pages in the user's browser (DNS
   rebinding, cross-site requests) or other processes could try to read files
   through it, or a request could try to escape the served folder.
5. **Injected markup.** Part names, colours or metadata ending up in HTML or SVG.
6. **Supply chain.** Python packages and the one external browser script.

## Mitigations implemented

| Risk | Mitigation | Where |
|---|---|---|
| Printer control | No code path talks to a printer: no G-code writer, no network client, no serial access. SKILL.md and references/safety.md tell Claude to stop at STL + print sheet. | `SKILL.md`, `references/safety.md` |
| Untrusted STL | Parsed as numbers only (trimesh/numpy, or `struct` in the SVG renderer); the 80-byte header and ASCII solid names are ignored; file size capped at 300 MB, SVG preview capped at 2 million triangles; only `.stl` accepted by the CLI. | `scripts/printcheck.py`, `scripts/svg_preview.py` |
| Prompt injection | SKILL.md and safety.md treat every supplied file as data and tell Claude to quote embedded instructions to the user instead of acting on them. | `SKILL.md`, `references/safety.md` |
| Path traversal on outputs | Part names must fully match `^[a-z0-9][a-z0-9-]{0,63}$`; output folders are resolved and refused if outside the project folder (symlinks included). `fits.json` is written only in the current folder. | `scripts/cad.py` (`validate_name`, `safe_out_dir`), `templates/build.py`, `scripts/calibration_coupon.py` |
| Bad exports | The template harness writes nothing unless printcheck has no errors. | `templates/build.py` |
| Preview server exposure | Binds `127.0.0.1` only (no option to change it), free port by default; GET/HEAD only; Host header must be `127.0.0.1:<port>` or `localhost:<port>` (blocks DNS rebinding); serves only fixed viewer files plus plain files directly inside one folder with an allow-listed extension (`.stl .json .svg .png`); refuses `..`, encoded slashes, backslashes, NUL, subfolders and symlinks; no directory listing. | `scripts/serve.py` |
| Browser hardening | Strict CSP on the page (`script-src 'self' https://cdnjs.cloudflare.com`, no inline script, `connect-src 'self'`, `frame-ancestors 'none'`), `sandbox` CSP on served files, `nosniff`, `no-referrer`, `no-store`, `X-Frame-Options: DENY`. | `scripts/serve.py` |
| Markup injection | The viewer builds the DOM with `textContent` only (a test fails on `innerHTML`, `eval`, `document.write`); file names and colours from the manifest are re-validated in the browser; the SVG renderer escapes its only text with `html.escape(..., quote=True)` and accepts only `#rrggbb` colours; manifest colours from metadata are validated. | `scripts/viewer/viewer.js`, `scripts/svg_preview.py`, `scripts/serve.py` |
| External script | Only three.js r128 from cdnjs, exact version, with a Subresource Integrity hash (`sha512`). The STL parser and orbit control are written in `viewer.js`, so no other library is fetched or vendored. Offline, the viewer falls back to server-rendered SVG. | `scripts/viewer/index.html` |
| Subprocesses | Headless Chrome is started with an argument list (never a shell), a throw-away profile directory, and is stopped by the script. | `scripts/render_png.py` |
| Python dependencies | Exact versions pinned. | `requirements.txt` |
| Secrets and personal data | None are needed or stored; no telemetry; nothing is sent anywhere. | whole repo |

Security tests live in `tests/` (malicious names, traversal paths, foreign
Host headers, hostile STL headers, hostile colours and titles, write methods).

## Residual risks

- Dependencies are pinned by version, not by hash; a compromised release on
  PyPI at the same version is not detected.
- While `serve.py` runs, any local process of any user on the same machine can
  read the served folder through the loopback port. Stop it when done.
- `serve.py` writes `manifest.json` into the served folder.
- trimesh and manifold3d are native/compiled code parsing and processing
  geometry; a crafted STL could still trigger a bug in them. Do not run the
  checks on files from sources you do not trust more than any other document.
- The safety advice in the references is general guidance, not certification.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting on this repository
(Security tab, "Report a vulnerability"). Do not open a public issue for
security problems.
