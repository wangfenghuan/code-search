import tempfile
import unittest
from pathlib import Path
from code_search_mcp.indexer import CodeIndexer
from code_search_mcp.outline import ProjectOutlineGenerator


class TestGitignoreAndSingleParse(unittest.TestCase):
    def test_gitignore_filtering(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Create .gitignore
            (root / ".gitignore").write_text("ignored_dir/\n*.generated.py\nsecret_mock/\n")

            # Create normal files
            (root / "app.py").write_text("def main():\n    pass\n")
            (root / "utils.js").write_text("function add(a, b) { return a + b; }\n")

            # Create files that should be ignored by .gitignore
            (root / "bad.generated.py").write_text("def generated():\n    pass\n")
            
            ign_dir = root / "ignored_dir"
            ign_dir.mkdir()
            (ign_dir / "inside_ignored.py").write_text("def secret():\n    pass\n")

            mock_dir = root / "secret_mock"
            mock_dir.mkdir()
            (mock_dir / "mock_service.ts").write_text("export const mock = 1;\n")

            # Create hardcoded ignored folder (e.g. node_modules)
            nm = root / "node_modules"
            nm.mkdir()
            (nm / "package.js").write_text("module.exports = {};\n")

            indexer = CodeIndexer(root)
            scanned = indexer.scan_files()
            scanned_names = {f.name for f in scanned}

            # Normal files must be present
            self.assertIn("app.py", scanned_names)
            self.assertIn("utils.js", scanned_names)

            # Ignored files must NOT be present
            self.assertNotIn("bad.generated.py", scanned_names)
            self.assertNotIn("inside_ignored.py", scanned_names)
            self.assertNotIn("mock_service.ts", scanned_names)
            self.assertNotIn("package.js", scanned_names)

    def test_single_parse_outline_generation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "calc.py").write_text(
                "class Calculator:\n    def add(self, a, b):\n        return a + b\n\ndef helper():\n    pass\n"
            )

            indexer = CodeIndexer(root)
            res = indexer.index_all(skip_vector=True)
            self.assertEqual(res["indexed_files"], 1)

            # Verify outline was generated directly into cache from SQLite nodes
            outline_gen = ProjectOutlineGenerator(root)
            cached_outline = outline_gen.get_cached_or_generate()
            self.assertEqual(cached_outline["total_modules"], 1)
            mod = cached_outline["modules"][0]
            self.assertEqual(mod["rel_path"], "calc.py")
            self.assertEqual(len(mod["classes"]), 1)
            self.assertEqual(mod["classes"][0]["name"], "Calculator")
            self.assertEqual(mod["classes"][0]["methods"], ["add"])


if __name__ == "__main__":
    unittest.main()
