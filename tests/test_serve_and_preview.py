import http.client
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import serve  # noqa: E402
import svg_preview  # noqa: E402

TINY_ASCII_STL = """solid t
facet normal 0 0 -1
 outer loop
  vertex 0 0 0
  vertex 0 10 0
  vertex 10 0 0
 endloop
endfacet
facet normal 0 0 1
 outer loop
  vertex 0 0 0
  vertex 10 0 0
  vertex 0 0 10
 endloop
endfacet
facet normal 0 1 0
 outer loop
  vertex 0 0 0
  vertex 0 0 10
  vertex 0 10 0
 endloop
endfacet
facet normal 1 1 1
 outer loop
  vertex 10 0 0
  vertex 0 10 0
  vertex 0 0 10
 endloop
endfacet
endsolid t
"""


class ServeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        cls.folder = base / "out"
        cls.folder.mkdir()
        (cls.folder / "part.stl").write_text(TINY_ASCII_STL)
        (cls.folder / "part.json").write_text(json.dumps({"preview_color": "red;}</style><script>",
                                                          "printer_bed": [180, 180, 180]}))
        (cls.folder / "notes.txt").write_text("not served")
        (base / "secret.stl").write_text("outside the served folder")
        (cls.folder / "link.stl").symlink_to(base / "secret.stl")
        sub = cls.folder / "sub"
        sub.mkdir()
        (sub / "deep.stl").write_text(TINY_ASCII_STL)
        cls.server, cls.url = serve.serve_in_thread(cls.folder, quiet=True)
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def get(self, path, host=None, method="GET"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        conn.putheader("Host", host or f"127.0.0.1:{self.port}")
        conn.endheaders()
        resp = conn.getresponse()
        body = resp.read()
        headers = dict(resp.getheaders())
        conn.close()
        return resp.status, headers, body

    def test_binds_loopback_only(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.assertTrue(self.url.startswith("http://127.0.0.1:"))

    def test_serves_viewer_and_files(self):
        status, headers, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("Content-Security-Policy", headers)
        self.assertIn(b"three.js/r128/three.min.js", body)
        self.assertEqual(self.get("/files/part.stl")[0], 200)

    def test_manifest(self):
        status, _, body = self.get("/manifest.json")
        self.assertEqual(status, 200)
        manifest = json.loads(body)
        self.assertEqual([p["file"] for p in manifest["parts"]], ["part.stl"])
        self.assertRegex(manifest["parts"][0]["color"], r"^#[0-9a-fA-F]{6}$")  # hostile colour dropped
        self.assertEqual(manifest["bed"], [180.0, 180.0, 180.0])
        self.assertTrue((self.folder / "manifest.json").is_file())

    def test_refuses_traversal_and_other_files(self):
        for path in ("/files/../secret.stl", "/files/..%2Fsecret.stl", "/files/%2e%2e/secret.stl",
                     "/../secret.stl", "/files/sub/deep.stl", "/files/sub%2Fdeep.stl", "/files/notes.txt",
                     "/files/link.stl", "/files/", "/files/.%2e/secret.stl", "/files/part.stl%00.png",
                     "/preview/..%2Fsecret.svg", "//etc/passwd", "/files/..\\secret.stl"):
            with self.subTest(path=path):
                status, _, body = self.get(path)
                self.assertIn(status, (400, 404), path)
                self.assertNotIn(b"outside the served folder", body)

    def test_rejects_foreign_host_header(self):
        status, _, _ = self.get("/", host="evil.example")
        self.assertEqual(status, 403)
        status, _, _ = self.get("/", host=f"localhost:{self.port}")
        self.assertEqual(status, 200)

    def test_rejects_writes(self):
        self.assertEqual(self.get("/files/part.stl", method="POST")[0], 405)
        self.assertEqual(self.get("/files/part.stl", method="PUT")[0], 405)

    def test_svg_preview_route(self):
        status, headers, body = self.get("/preview/part.svg")
        self.assertEqual(status, 200)
        self.assertIn("sandbox", headers["Content-Security-Policy"])
        self.assertNotIn(b"<script", body)

    def test_bad_colour_option_refused(self):
        with self.assertRaises(ValueError):
            serve.make_server(self.folder, colors={"part": "javascript:alert(1)"})

    def test_no_host_option_exists(self):
        self.assertEqual(serve.HOST, "127.0.0.1")
        import contextlib
        import io
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            serve.main([str(self.folder), "--host", "0.0.0.0"])


class ViewerSourceTests(unittest.TestCase):
    def test_viewer_builds_dom_without_innerhtml(self):
        js = (ROOT / "scripts" / "viewer" / "viewer.js").read_text()
        self.assertNotIn("innerHTML", js)
        self.assertNotIn("eval(", js)
        self.assertNotIn("document.write", js)

    def test_only_pinned_cdnjs_script(self):
        page = (ROOT / "scripts" / "viewer" / "index.html").read_text()
        external = re.findall(r'src="(https?://[^"]+)"', page)
        self.assertEqual(external, ["https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"])
        self.assertIn('integrity="sha512-', page)


class SvgPreviewTests(unittest.TestCase):
    def test_title_is_escaped(self):
        with tempfile.TemporaryDirectory() as tmp:
            stl = Path(tmp) / "t.stl"
            stl.write_text(TINY_ASCII_STL)
            svg = svg_preview.render_svg(stl, title='<script>alert("x")</script>', color="#ff0000")
            self.assertNotIn("<script", svg)
            self.assertIn("&lt;script&gt;", svg)
            self.assertIn("<polygon", svg)
            bad = svg_preview.render_svg(stl, color='"/><script>', background="url(javascript:1)")
            self.assertNotIn("<script", bad)
            self.assertNotIn("javascript", bad)


if __name__ == "__main__":
    unittest.main()
