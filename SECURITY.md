# Security

## Scope and threat model

This skill runs on the user's own machine. It writes geometry files and runs a
short-lived local preview server. The things that could go wrong:

1. **Physical harm through a printer.** A tool that drives a printer can start
   a job unattended or with wrong temperatures.
2. **Code planted next to a build script.** Python imports modules from the
   script's own folder first, so a `cad.py`, `argparse.py` or `pathlib.py`
   sitting in a downloaded or cloned folder could run as soon as `build.py`
   starts.
3. **Untrusted input files.** STL files, images, PDFs or web pages the user
   supplies may be malformed, huge, or carry text aimed at the assistant
   (prompt injection) in names, headers or comments. File names may contain
   terminal escape sequences.
4. **Path and symlink tricks.** A part name or output folder such as
   `../../.ssh/x`, or a symlink planted where an output file will be written,
   could make a write land outside the project (for example on
   `~/.ssh/authorized_keys`).
5. **The local preview server.** Other web pages in the user's browser (DNS
   rebinding, cross-site requests) or other processes could try to read files
   through it, escape the served folder, or tie it up.
6. **Injected markup.** Part names, colours or metadata ending up in HTML or SVG.
7. **Resource exhaustion.** Huge or pathological meshes making the checks or
   the SVG fallback take minutes or gigabytes.
8. **Supply chain.** Python packages, CI actions and the one external browser script.

## Mitigations implemented

| Risk | Mitigation | Where |
|---|---|---|
| Printer control | No code path talks to a printer: no G-code writer, no network client, no serial access. SKILL.md and references/safety.md tell Claude to stop at STL + print sheet. | `SKILL.md`, `references/safety.md` |
| Planted modules | The first statements of every build script (after `import os, sys`, both already loaded by the interpreter) remove the script's own folder from `sys.path` (compared with `realpath`; skipped when `sys.flags.safe_path` is set). Helpers are loaded only from `$PRINT3D_SKILL_DIR/scripts` or `~/.claude/skills/3d-print-design/scripts`; folders around the project are never searched. SKILL.md and README use `python -P`, a fresh empty project folder (never inside a downloaded or cloned repository) and copying supplied STLs into it as data. CI sets `PRINT3D_SKILL_DIR` from `$GITHUB_WORKSPACE`. | `templates/build.py`, `examples/cable-clip/build.py`, `SKILL.md`, `README.md`, `.github/workflows/ci.yml` |
| Symlinked or swapped output files | One helper, `safeio.atomic_write`, does every write: it refuses a target that is a symlink or not a regular file, writes a new temp file in the same folder with `O_CREAT \| O_EXCL \| O_NOFOLLOW` (mode 0o644), fsyncs it and `os.replace()`s it over the target. `rename()` replaces the directory entry and never follows a link, so a link planted between the check and the rename is replaced, not followed. Used for STL + JSON exports, `fits.json`, `manifest.json`, `--out` SVGs and PNGs (Chrome writes into a private temp folder; the result is then moved into place). | `scripts/safeio.py`, `scripts/cad.py`, `scripts/calibration_coupon.py`, `scripts/serve.py`, `scripts/svg_preview.py`, `scripts/render_png.py` |
| Path traversal on outputs | Part names must fully match `^[a-z0-9][a-z0-9-]{0,63}$` (`fullmatch`, so a trailing newline is refused); output folders are resolved and refused if outside the project folder (symlinked folders included). `render_png.py` uses `abspath`, not `resolve`, so it never follows a symlinked output. | `scripts/cad.py` (`validate_name`, `safe_out_dir`), `templates/build.py`, `scripts/render_png.py` |
| Bad exports | The template harness writes nothing unless printcheck has no errors. | `templates/build.py` |
| Untrusted STL | Parsed as numbers only; the 80-byte header and ASCII solid names are ignored. Size caps are checked from the file size before anything is read: 300 MB for printcheck and the server, 128 MB for the pure-Python SVG renderer, which also caps triangles at 500,000 (from the binary header, or counted while an ASCII file is streamed line by line, stopping as soon as the cap is passed). The same caps apply to the `/preview` route and to `render_png.py`'s fallback. | `scripts/printcheck.py`, `scripts/svg_preview.py`, `scripts/serve.py`, `scripts/render_png.py` |
| Slow checks | Connected components (bodies, flat regions) use vectorised labelling; bridge classification aggregates per region with `bincount` and measures only wide regions with shapely (at most 200); hole sections over 20,000 edges are skipped and reported; ray sampling is capped at 3e8 triangle tests. A mesh with 20,000 separate flat regions checks in about a second. | `scripts/printcheck.py` |
| Terminal escape sequences | File names, paths and request paths are stripped of control and format characters (Unicode category C: C0/C1 controls, bidi overrides, zero-width characters) and truncated before they are printed or logged. | `scripts/safeio.py` (`safe_text`), `scripts/printcheck.py`, `scripts/serve.py`, the other CLIs |
| Prompt injection | SKILL.md and safety.md treat every supplied file as data and tell Claude to quote embedded instructions to the user instead of acting on them. | `SKILL.md`, `references/safety.md` |
| Preview server exposure | Binds `127.0.0.1` only (no option to change it), free port by default; GET/HEAD only; Host header must be `127.0.0.1:<port>` or `localhost:<port>` (blocks DNS rebinding); 15 s socket timeout per connection; serves only fixed viewer files plus plain files directly inside one folder with an allow-listed extension (`.stl .json .svg .png`); refuses `..`, encoded slashes, backslashes, NUL and subfolders; no directory listing. Each file is opened with `O_NOFOLLOW \| O_NONBLOCK` relative to a directory descriptor taken at start-up, then `fstat`-checked on the open descriptor: only a regular file with one link and within the size cap is read, streamed from that same descriptor. Symlinks, hard links to files elsewhere and FIFOs are refused, and nothing can be swapped between check and read. `/manifest.json` is built in memory per request; the file on disk is written once at start-up. | `scripts/serve.py` |
| Browser hardening | Strict CSP on the page (`script-src 'self'` plus the exact three.js URL, no inline script, `connect-src 'self'`, `frame-ancestors 'none'`), `sandbox` CSP on served files, `nosniff`, `no-referrer`, `no-store`, `X-Frame-Options: DENY`. | `scripts/serve.py` |
| Markup injection | The viewer builds the DOM with `textContent` only (a test fails on `innerHTML`, `eval`, `document.write`); file names and colours from the manifest are re-validated in the browser; the SVG renderer escapes its only text with `html.escape(..., quote=True)` and accepts only `#rrggbb` colours; manifest colours from metadata are validated. | `scripts/viewer/viewer.js`, `scripts/svg_preview.py`, `scripts/serve.py` |
| External script | Only three.js r128 from cdnjs, exact version, with a Subresource Integrity hash (`sha512`). The STL parser and orbit control are written in `viewer.js`, so no other library is fetched or vendored. Offline, the viewer falls back to server-rendered SVG. | `scripts/viewer/index.html` |
| Subprocesses | Headless Chrome is started with an argument list (never a shell), a throw-away profile directory, and is stopped by the script. | `scripts/render_png.py` |
| Python dependencies and CI | Exact versions pinned; CI installs only `requirements.txt` (no unpinned pip upgrade) and uses actions pinned by commit SHA with read-only permissions. | `requirements.txt`, `.github/workflows/ci.yml` |
| Secrets and personal data | None are needed or stored; no telemetry; nothing is sent anywhere. | whole repo |

Security tests live in `tests/`: malicious names, traversal paths, foreign Host
headers, hostile STL headers, colours and titles, write methods, planted
modules in the project and parent folders, symlinked output targets for every
writer, oversize and over-count STLs, a many-region mesh, control characters in
file names, and symlinked, hard-linked and FIFO files in the served folder.

## Residual risks

- Dependencies are pinned by version, not by hash; a compromised release on
  PyPI at the same version is not detected.
- While `serve.py` runs, any local process of any user on the same machine can
  read the served folder through the loopback port. Stop it when done.
- `atomic_write` protects the final path component. If the user points an
  output at a folder that is itself a symlink, the write goes where that link
  points; build outputs are additionally confined to the project folder.
- On platforms without `O_NOFOLLOW` (Windows), the server falls back to a
  resolve-and-compare check, which has a small time-of-check gap.
- trimesh and manifold3d are compiled code parsing and processing geometry; a
  crafted STL could still trigger a bug in them. Do not run the checks on files
  from sources you do not trust more than any other document.
- Python code the user (or Claude) writes in a project's GEOMETRY block runs
  with the user's rights, like any script.
- The safety advice in the references is general guidance, not certification.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting on this repository
(Security tab, "Report a vulnerability"). Do not open a public issue for
security problems.
