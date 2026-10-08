"""Regression tests for the security review findings (planted modules, symlinked
writes, size caps before reading, many-region performance, control characters,
O_NOFOLLOW serving, server hardening, CI hygiene)."""
import contextlib
import io
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402
import trimesh  # noqa: E402

import cad  # noqa: E402
import calibration_coupon  # noqa: E402
import printcheck  # noqa: E402
import render_png  # noqa: E402
import safeio  # noqa: E402
import serve  # noqa: E402
import svg_preview  # noqa: E402

PLANTED = (
    "import os\n"
    "with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'PWNED'), 'a') as f:\n"
    "    f.write(__name__ + '\\n')\n"
    "raise SystemExit(99)\n"
)
TRI = "facet normal 0 0 1\n outer loop\n  vertex 0 0 0\n  vertex 1 0 0\n  vertex 0 1 0\n endloop\nendfacet\n"
HARNESS_MARK = "# ============ HARNESS: DO NOT EDIT BELOW THIS LINE ============"
PARAMS_MARK = "# ===================== PARAMETERS START"


def ascii_stl(n):
    return "solid t\n" + TRI * n + "endsolid t\n"


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(os.path.realpath(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()


# ---------------------------------------------------------------- MEDIUM 1
class PlantedModuleTests(TempDirCase):
    SOURCES = (ROOT / "templates" / "build.py", ROOT / "examples" / "cable-clip" / "build.py")

    def run_build(self, project, env_extra, *flags):
        env = {k: v for k, v in os.environ.items() if k != "PRINT3D_SKILL_DIR"}
        env["HOME"] = str(self.tmp / "home")  # no installed skill there
        env.update(env_extra)
        return subprocess.run([sys.executable, *flags, "build.py", "--check", "--thin-walls", "0"],
                              cwd=project, env=env, capture_output=True, text=True, timeout=300)

    def test_modules_planted_in_the_project_folder_never_run(self):
        for src in self.SOURCES:
            with self.subTest(script=src.parent.name):
                project = self.tmp / src.parent.name / "project"
                project.mkdir(parents=True)
                shutil.copy(src, project / "build.py")
                for mod in ("argparse", "pathlib", "cad", "printcheck", "safeio", "numpy", "trimesh"):
                    (project / f"{mod}.py").write_text(PLANTED)
                for flags in ((), ("-P",)):
                    res = self.run_build(project, {"PRINT3D_SKILL_DIR": str(ROOT)}, *flags)
                    self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
                    self.assertFalse((project / "PWNED").exists(), (project / "PWNED").read_text()
                                     if (project / "PWNED").exists() else "")

    def test_scripts_folders_above_the_project_are_never_searched(self):
        for src in self.SOURCES:
            with self.subTest(script=src.parent.name):
                grand = self.tmp / src.parent.name / "cloned-repo"
                project = grand / "examples" / "project"
                project.mkdir(parents=True)
                shutil.copy(src, project / "build.py")
                for folder in (grand / "scripts", grand / "examples" / "scripts"):
                    folder.mkdir(parents=True, exist_ok=True)
                    for mod in ("cad", "printcheck", "safeio"):
                        (folder / f"{mod}.py").write_text(PLANTED)
                res = self.run_build(project, {})
                self.assertNotEqual(res.returncode, 0)
                self.assertIn("cannot find the 3d-print-design scripts", res.stderr)
                res = self.run_build(project, {"PRINT3D_SKILL_DIR": str(ROOT)})
                self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
                for folder in (grand / "scripts", grand / "examples" / "scripts"):
                    self.assertFalse((folder / "PWNED").exists())

    def test_examples_keep_the_template_header(self):
        def header(text):
            return text[text.index("\nimport os\n"):text.index(PARAMS_MARK)]
        tpl = (ROOT / "templates" / "build.py").read_text()
        self.assertIn('if not getattr(sys.flags, "safe_path", False):', header(tpl))
        self.assertNotIn("here.parent", tpl)
        for build in (ROOT / "examples").glob("*/build.py"):
            text = build.read_text()
            self.assertEqual(header(text), header(tpl))
            self.assertEqual(text.split(HARNESS_MARK)[1], tpl.split(HARNESS_MARK)[1])


# ---------------------------------------------------------------- MEDIUM 2
class AtomicWriteTests(TempDirCase):
    def setUp(self):
        super().setUp()
        self.victim = self.tmp / "authorized_keys"
        self.victim.write_text("ORIGINAL\n")

    def assert_untouched(self):
        self.assertEqual(self.victim.read_text(), "ORIGINAL\n")

    def test_helper_refuses_symlink_and_replaces_regular_files(self):
        link = self.tmp / "out.json"
        link.symlink_to(self.victim)
        with self.assertRaises(ValueError):
            safeio.atomic_write(link, "x")
        self.assert_untouched()
        target = self.tmp / "plain.json"
        target.write_text("old")
        safeio.atomic_write(target, "new")
        self.assertEqual(target.read_text(), "new")
        self.assertEqual(stat.S_IMODE(target.stat().st_mode) & 0o022, 0)
        (self.tmp / "dir.json").mkdir()
        with self.assertRaises(ValueError):
            safeio.atomic_write(self.tmp / "dir.json", "x")
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir() if p.name.endswith(".tmp")), [])

    def test_link_planted_after_the_check_is_replaced_not_followed(self):
        target = self.tmp / "race.json"
        real_replace = os.replace

        def swap_then_replace(src, dst):
            os.symlink(self.victim, dst)  # attacker wins the race
            return real_replace(src, dst)

        with mock.patch("safeio.os.replace", side_effect=swap_then_replace):
            safeio.atomic_write(target, "new")
        self.assert_untouched()
        self.assertFalse(target.is_symlink())
        self.assertEqual(target.read_text(), "new")

    def test_write_part_refuses_symlinked_stl_or_json(self):
        mesh = cad.to_trimesh(cad.box(10, 10, 10))
        res = printcheck.check_printable(mesh)
        for suffix in (".stl", ".json"):
            with self.subTest(suffix=suffix):
                out = self.tmp / f"out{suffix}"
                out.mkdir()
                (out / f"part{suffix}").symlink_to(self.victim)
                with self.assertRaises(ValueError):
                    cad.write_part(out, "part", mesh, res)
                self.assert_untouched()
                self.assertFalse((out / "part.stl").is_file() and not (out / "part.stl").is_symlink())

    def test_template_refuses_symlinked_output(self):
        project = self.tmp / "project"
        (project / "out").mkdir(parents=True)
        shutil.copy(ROOT / "templates" / "build.py", project / "build.py")
        (project / "out" / "mounting-plate.json").symlink_to(self.victim)
        res = subprocess.run([sys.executable, "-P", "build.py", "--thin-walls", "0"], cwd=project,
                             env=dict(os.environ, PRINT3D_SKILL_DIR=str(ROOT)),
                             capture_output=True, text=True, timeout=300)
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        self.assertIn("symlink", res.stderr)
        self.assert_untouched()

    def test_fits_record_refuses_symlink(self):
        (self.tmp / "fits.json").symlink_to(self.victim)
        old = os.getcwd()
        os.chdir(self.tmp)
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = calibration_coupon.main(["record", "--press", "0.1"])
        finally:
            os.chdir(old)
        self.assertEqual(code, 2)
        self.assert_untouched()

    def test_manifest_symlink_refused_at_start(self):
        folder = self.tmp / "out"
        folder.mkdir()
        (folder / "part.stl").write_text(ascii_stl(2))
        (folder / "manifest.json").symlink_to(self.victim)
        with self.assertRaises(ValueError):
            serve.make_server(folder, quiet=True)
        self.assert_untouched()

    def test_get_manifest_never_writes(self):
        folder = self.tmp / "out"
        folder.mkdir()
        (folder / "part.stl").write_text(ascii_stl(2))
        server, _ = serve.serve_in_thread(folder, quiet=True)
        try:
            (folder / "manifest.json").unlink()
            (folder / "manifest.json").symlink_to(self.victim)
            port = server.server_address[1]
            body = _http(port, "/manifest.json")[2]
            self.assertEqual(json.loads(body)["parts"][0]["file"], "part.stl")
        finally:
            server.shutdown()
            server.server_close()
        self.assert_untouched()

    def test_svg_preview_out_refuses_symlink(self):
        stl = self.tmp / "p.stl"
        stl.write_text(ascii_stl(2))
        (self.tmp / "o.svg").symlink_to(self.victim)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = svg_preview.main([str(stl), "--out", str(self.tmp / "o.svg")])
        self.assertEqual(code, 2)
        self.assert_untouched()

    def test_render_png_refuses_symlinked_png_or_svg(self):
        folder = self.tmp / "out"
        folder.mkdir()
        (folder / "part.stl").write_text(ascii_stl(4))
        for name in ("shot.png", "shot.svg"):
            with self.subTest(name=name):
                docs = self.tmp / f"docs-{name}"
                docs.mkdir()
                (docs / name).symlink_to(self.victim)
                with mock.patch.object(render_png, "find_chrome", return_value=None):
                    with self.assertRaises(ValueError):
                        render_png.render(folder, docs / "shot.png", force_svg=True)
                self.assert_untouched()

    def test_render_png_writes_svg_atomically_without_chrome(self):
        folder = self.tmp / "out"
        folder.mkdir()
        (folder / "part.stl").write_text(ascii_stl(4))
        with mock.patch.object(render_png, "find_chrome", return_value=None):
            method, path = render_png.render(folder, self.tmp / "shot.png", force_svg=True)
        self.assertEqual(method, "svg-only")
        self.assertIn("<polygon", Path(path).read_text())


# ---------------------------------------------------------------- LOW 3
class SizeCapTests(TempDirCase):
    def test_oversize_file_rejected_before_reading(self):
        big = self.tmp / "big.stl"
        big.write_text(ascii_stl(50))
        with mock.patch.object(svg_preview, "MAX_STL_BYTES", 100), \
                mock.patch("builtins.open", side_effect=AssertionError("file was opened")):
            with self.assertRaises(ValueError):
                svg_preview.read_stl(big)

    def test_ascii_triangle_cap_stops_reading_early(self):
        data = ascii_stl(1000).encode()

        class Counting(io.BytesIO):
            lines = 0

            def readline(self, *a):
                Counting.lines += 1
                return super().readline(*a)

        fh = Counting(data)
        with mock.patch.object(svg_preview, "MAX_TRIANGLES", 5):
            with self.assertRaises(ValueError):
                svg_preview.read_stl(fh)
        self.assertLess(Counting.lines, 100)  # stopped near triangle 6, not at line 7000

    def test_binary_triangle_cap_from_header(self):
        m = cad.to_trimesh(cad.box(10, 10, 10))
        path = self.tmp / "b.stl"
        path.write_bytes(m.export(file_type="stl"))
        with mock.patch.object(svg_preview, "MAX_TRIANGLES", 3):
            with self.assertRaises(ValueError):
                svg_preview.read_stl(path)
        self.assertEqual(len(svg_preview.read_stl(path)), 9 * len(m.faces))

    def test_preview_route_and_render_png_respect_the_cap(self):
        folder = self.tmp / "out"
        folder.mkdir()
        (folder / "big.stl").write_text(ascii_stl(50))
        server, _ = serve.serve_in_thread(folder, quiet=True)
        try:
            with mock.patch.object(svg_preview, "MAX_STL_BYTES", 100):
                self.assertIn(_http(server.server_address[1], "/preview/big.svg")[0], (404, 413))
                with self.assertRaises(ValueError):
                    render_png._fallback_svg(server, "iso", "light", 800, 600)
            with mock.patch.object(svg_preview, "MAX_TRIANGLES", 10):
                self.assertEqual(_http(server.server_address[1], "/preview/big.svg")[0], 413)
        finally:
            server.shutdown()
            server.server_close()


# ---------------------------------------------------------------- LOW 4
class ManyRegionTests(unittest.TestCase):
    def test_twenty_thousand_flat_regions_finish_fast(self):
        n_side, size = 142, 0.6
        b = trimesh.creation.box((size, size, size))
        xs, ys = np.meshgrid(np.arange(n_side) * 1.0, np.arange(n_side) * 1.0)
        offs = np.c_[xs.ravel(), ys.ravel(), np.full(xs.size, 1.0 + size / 2)]
        verts = (b.vertices[None] + offs[:, None]).reshape(-1, 3)
        faces = (b.faces[None] + (np.arange(len(offs)) * len(b.vertices))[:, None, None]).reshape(-1, 3)
        boxes = trimesh.Trimesh(verts, faces, process=False)
        base = trimesh.creation.box((n_side + 2, n_side + 2, 1.0))
        base.apply_translation((n_side / 2 - 0.5, n_side / 2 - 0.5, 0.5))
        mesh = trimesh.util.concatenate([boxes, base])
        t = time.monotonic()
        r = printcheck.check_printable(mesh, expected_bodies=None, bed=(400, 400, 400))
        elapsed = time.monotonic() - t
        self.assertLess(elapsed, 20.0)
        self.assertEqual(r.stats["bodies"], n_side * n_side + 1)
        self.assertAlmostEqual(r.get("overhang").data["area_mm2"], n_side * n_side * size * size, delta=1.0)
        self.assertEqual(r.get("on_bed").status, "fail")


# ---------------------------------------------------------------- LOW 5
class ControlCharacterTests(TempDirCase):
    def test_safe_text_strips_controls_and_format_chars(self):
        self.assertEqual(safeio.safe_text("a\x1b[31mb\x07\x9b\u202ec\u200bd\n"), "a[31mbcd")
        self.assertEqual(len(safeio.safe_text("x" * 500, 50)), 50)

    def test_printcheck_cli_prints_a_clean_name(self):
        name = "evil\x1b]0;title\x07\x1b[2J\u202ename.stl"
        path = self.tmp / name
        cad.to_trimesh(cad.box(10, 10, 10)).export(path)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = printcheck.main([str(path)])
        self.assertEqual(code, 0)
        for bad in ("\x1b", "\x07", "\u202e"):
            self.assertNotIn(bad, out.getvalue() + err.getvalue())
        self.assertIn("evil", out.getvalue())

    def test_server_log_is_sanitised(self):
        folder = self.tmp / "out"
        folder.mkdir()
        (folder / "a.stl").write_text(ascii_stl(2))
        server, _ = serve.serve_in_thread(folder, quiet=False)
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                port = server.server_address[1]
                with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
                    s.sendall(b"GET /files/\x1b[2Jx\x07.stl HTTP/1.0\r\nHost: 127.0.0.1:%d\r\n\r\n" % port)
                    s.recv(4096)
                time.sleep(0.2)
        finally:
            server.shutdown()
            server.server_close()
        self.assertIn("serve:", err.getvalue())
        self.assertNotIn("\x1b", err.getvalue())
        self.assertNotIn("\x07", err.getvalue())


# ---------------------------------------------------------------- INFO items
class ServingTests(TempDirCase):
    def setUp(self):
        super().setUp()
        self.folder = self.tmp / "out"
        self.folder.mkdir()
        (self.folder / "a.stl").write_text(ascii_stl(2))
        outside = self.tmp / "outside.stl"
        outside.write_text("SECRET OUTSIDE")
        os.link(outside, self.folder / "hard.stl")
        os.mkfifo(self.folder / "fifo.stl")
        (self.folder / "link.stl").symlink_to(outside)

    def test_open_child_uses_o_nofollow(self):
        seen = []
        real_open = os.open

        def spy(path, flags, *a, **kw):
            seen.append(flags)
            return real_open(path, flags, *a, **kw)

        with mock.patch("serve.os.open", side_effect=spy):
            opened = serve.open_child(self.folder, "a.stl")
        self.assertIsNotNone(opened)
        opened[0].close()
        self.assertTrue(seen and all(f & os.O_NOFOLLOW for f in seen))

    def test_symlink_hardlink_and_fifo_refused(self):
        for name in ("link.stl", "hard.stl", "fifo.stl"):
            with self.subTest(name=name):
                t = time.monotonic()
                self.assertIsNone(serve.open_child(self.folder, name))
                self.assertLess(time.monotonic() - t, 2.0)  # a FIFO must not block
        server, _ = serve.serve_in_thread(self.folder, quiet=True)
        try:
            port = server.server_address[1]
            for name in ("link.stl", "hard.stl", "fifo.stl"):
                status, _, body = _http(port, f"/files/{name}")
                self.assertEqual(status, 404)
                self.assertNotIn(b"SECRET", body)
            names = [p["file"] for p in json.loads(_http(port, "/manifest.json")[2])["parts"]]
            self.assertEqual(names, ["a.stl"])
        finally:
            server.shutdown()
            server.server_close()

    def test_directory_is_pinned_at_start(self):
        server, _ = serve.serve_in_thread(self.folder, quiet=True)
        try:
            other = self.tmp / "other"
            other.mkdir()
            (other / "a.stl").write_text("SWAPPED")
            self.folder.rename(self.tmp / "moved")
            self.folder.symlink_to(other, target_is_directory=True)
            body = _http(server.server_address[1], "/files/a.stl")[2]
            self.assertNotIn(b"SWAPPED", body)
            self.assertIn(b"facet", body)
        finally:
            server.shutdown()
            server.server_close()

    def test_timeout_and_exact_csp(self):
        self.assertEqual(serve.PreviewHandler.timeout, 15)
        server, _ = serve.serve_in_thread(self.folder, quiet=True)
        try:
            _, headers, _ = _http(server.server_address[1], "/")
        finally:
            server.shutdown()
            server.server_close()
        csp = headers["Content-Security-Policy"]
        self.assertIn("script-src 'self' https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js;", csp)
        self.assertNotIn("https://cdnjs.cloudflare.com;", csp)


class CiHygieneTests(unittest.TestCase):
    def test_ci_pins_and_env(self):
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        self.assertNotIn("--upgrade pip", ci)
        self.assertIn('export PRINT3D_SKILL_DIR="$GITHUB_WORKSPACE"', ci)
        for line in ci.splitlines():
            if line.strip().startswith("- uses:"):
                self.assertRegex(line, r"@[0-9a-f]{40}\b")
        run_lines = [ln for ln in ci.splitlines() if "PRINT3D_SKILL_DIR" in ln]
        self.assertTrue(run_lines and all("${{" not in ln for ln in run_lines))


def _http(port, path):
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    headers = dict(resp.getheaders())
    conn.close()
    return resp.status, headers, body


if __name__ == "__main__":
    unittest.main()
