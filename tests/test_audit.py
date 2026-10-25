import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from recursion_claim_audit.audit import audit, extract_claims, extract_evidence, RECURSIVE, SHALLOW
from recursion_claim_audit.__main__ import main

FIXTURES = Path(__file__).parent / 'fixtures'


class Claims(unittest.TestCase):
    def test_fenced(self):
        self.assertEqual(extract_claims('```text\nscans recursively\n```'), [])

    def test_tilde_fenced(self):
        self.assertEqual(extract_claims('~~~\ntop-level only\n~~~'), [])

    def test_long_fence(self):
        self.assertEqual(extract_claims('````\n```\nrecursively\n````'), [])

    def test_inline(self):
        self.assertEqual(extract_claims('Uses `recursive scan`.')[0]['family'], 'recursive')

    def test_bare_noun(self):
        self.assertEqual(extract_claims('recursion support'), [])

    def test_negated_recursive(self):
        self.assertEqual(extract_claims('does not scan recursively'), [])

    def test_walks_adverb(self):
        self.assertEqual(extract_claims('walks recursively')[0]['family'], 'recursive')

    def test_negated_shallow(self):
        self.assertEqual(extract_claims('does not scan top-level only'), [])

    def test_negated_explicit(self):
        self.assertEqual([c['family'] for c in extract_claims('this tool is not recursive')], ['shallow'])

    def test_boundaries(self):
        self.assertEqual(extract_claims('non-recursively scanning; recursive scanner'), [])

    def test_sentence_scope(self):
        self.assertEqual(len(extract_claims('Not supported. Scans recursively.')), 1)

    def test_inline_dotted_name_negation(self):
        self.assertEqual(extract_claims('Does not use `os.walk` recursively.'), [])

    def test_multiline_negation(self):
        self.assertEqual(extract_claims('does not scan\nrecursively'), [])

    def test_multiline_phrase(self):
        self.assertEqual(extract_claims('Uses recursive\nscan.')[0]['line'], 1)

    def test_line_number(self):
        self.assertEqual(extract_claims('Hello.\n\nScans recursively.')[0]['line'], 3)


class Evidence(unittest.TestCase):
    def test_syntax_error(self):
        evidence, error = extract_evidence('def broken(', 'x.py')
        self.assertEqual(evidence, [])
        self.assertTrue(error)

    def test_nested_function_separate(self):
        source = 'def scan():\n    scan()\n    def inner():\n        os.listdir(".")\n'
        self.assertEqual(extract_evidence(source, 'x.py')[0], [])

    def test_dedupe(self):
        self.assertEqual(len(extract_evidence('os.walk("."); os.walk(".")', 'x.py')[0]), 1)


POSITIVE = {
 'os_walk': 'import os\nos.walk(".")',
 'import_walk': 'from os import walk\nwalk(".")',
 'alias_walk': 'from os import walk as descend\ndescend(".")',
 'alias_os': 'import os as operating\noperating.walk(".")',
 'legacy': 'os.path.walk(".", callback, None)',
 'rglob': 'Path(".").rglob("*.py")',
 'any_rglob': 'thing.rglob("*")',
 'glob_keyword': 'import glob\nglob.glob("*", recursive=True)',
 'glob_alias': 'from glob import glob as gg\ngg("*", recursive=True)',
 'glob_pattern': 'glob.glob("**/*.py")',
 'path_glob': 'path.glob("**/*.py")',
 'self_scandir': 'def scan(p):\n    for x in os.scandir(p):\n        scan(x.path)',
 'self_listdir': 'def scan(p):\n    os.listdir(p)\n    scan(p)',
 'self_iterdir': 'def scan(p):\n    p.iterdir()\n    scan(p)',
 'self_alias': 'from os import scandir as read\ndef scan(p):\n    read(p)\n    scan(p)',
 'dead_code': 'def unused():\n    os.walk(".")',
}
NEGATIVE = {
 'bare_walk': 'walk(".")',
 'flat_listdir': 'os.listdir(".")',
 'flat_scandir': 'os.scandir(".")',
 'flat_iterdir': 'path.iterdir()',
 'plain_glob': 'glob.glob("*.py")',
 'plain_path_glob': 'Path(".").glob("*.py")',
 'variable_recursive': 'glob.glob("*", recursive=setting)',
 'false_recursive': 'glob.glob("*", recursive=False)',
 'integer_recursive': 'glob.glob("*", recursive=1)',
 'non_glob_recursive': 'fetch("*", recursive=True)',
 'factorial': 'def fact(n):\n    return n * fact(n-1)',
 'fixed_directories': 'for p in ["a", "b"]:\n    os.listdir(p)',
 'pattern_variable': 'glob.glob(pattern)',
 'string_evidence': 'value = "os.walk()"',
}


def phrase_test(phrase, family):
    def test(self):
        self.assertEqual([c['family'] for c in extract_claims(phrase.upper())], [family])
    return test


for family, phrases in [('recursive', RECURSIVE), ('shallow', SHALLOW)]:
    for i, phrase in enumerate(phrases):
        setattr(Claims, 'test_phrase_' + family + '_' + str(i), phrase_test(phrase, family))


def evidence_test(source, positive):
    def test(self):
        evidence, error = extract_evidence(source, 'main.py')
        self.assertIsNone(error)
        self.assertEqual(bool(evidence), positive)
    return test


for positive, cases in [(True, POSITIVE), (False, NEGATIVE)]:
    for name, source in cases.items():
        setattr(Evidence, 'test_' + name, evidence_test(source, positive))


class Integration(unittest.TestCase):
    def make_tree(self, claim='scans recursively', source='import os\nos.listdir(".")'):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / 'README.md').write_text(claim)
        if source is not None:
            (root / 'main.py').write_text(source)
        return root

    def cli(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(list(map(str, args)))
        return code, output.getvalue()

    def test_good_recursive(self):
        result = audit(FIXTURES / 'good/recursive')
        self.assertEqual(result['findings'], [])
        self.assertEqual(result['verified_claims'][0]['family'], 'recursive')

    def test_good_shallow(self):
        self.assertEqual(audit(FIXTURES / 'good/shallow')['verified_claims'][0]['family'], 'shallow')

    def test_bad_recursive(self):
        findings = audit(FIXTURES / 'bad/recursive')['findings']
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]['rule'], 'documented-recursive-claim-false')
        self.assertEqual(findings[0]['severity'], 'HIGH')

    def test_bad_shallow(self):
        findings = audit(FIXTURES / 'bad/shallow')['findings']
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]['rule'], 'documented-shallow-claim-false')
        self.assertEqual(len(findings[0]['evidence']), 1)

    def test_testonly(self):
        code, output = self.cli(FIXTURES / 'testonly', '--json')
        finding = json.loads(output)['findings'][0]
        self.assertEqual(code, 2)
        self.assertEqual(finding['rule'], 'documented-recursive-claim-false-test-only')
        self.assertEqual(finding['severity'], 'MEDIUM')

    def test_high_threshold(self):
        code, output = self.cli(FIXTURES / 'testonly', '--fail-on', 'HIGH')
        self.assertEqual(code, 0)
        self.assertIn('MEDIUM', output)

    def test_ignore(self):
        root = self.make_tree(source='os.walk(".")')
        self.assertEqual(audit(root)['findings'], [])
        self.assertEqual(audit(root, ['main.py'])['findings'][0]['evidence'], [{'kind': 'no-source'}])

    def test_both_no_source(self):
        root = self.make_tree('Scans recursively. Top-level only.', None)
        findings = audit(root)['findings']
        self.assertEqual(len(findings), 2)
        self.assertTrue(all(f['severity'] == 'HIGH' and f['evidence'] == [{'kind': 'no-source'}] for f in findings))

    def test_both_testonly(self):
        root = self.make_tree('Scans recursively. Top-level only.')
        (root / 'tests').mkdir()
        (root / 'tests/test_x.py').write_text('os.walk(".")')
        self.assertEqual(len(audit(root)['findings']), 2)
        self.assertTrue(all(f['severity'] == 'MEDIUM' for f in audit(root)['findings']))

    def test_no_claim(self):
        self.assertEqual(audit(self.make_tree('A tool.', 'os.walk(".")'))['findings'], [])

    def test_shallow_all_evidence(self):
        root = self.make_tree('top-level only', 'os.walk(".")\np.rglob("*")')
        self.assertEqual(len(audit(root)['findings'][0]['evidence']), 2)

    def test_json_shape(self):
        code, output = self.cli(FIXTURES / 'good/recursive', '--json')
        self.assertEqual(code, 0)
        self.assertEqual(set(json.loads(output)), {'findings', 'verified_claims', 'errors'})

    def test_env_never_opened(self):
        original = Path.open
        def guarded(path, *args, **kwargs):
            self.assertNotEqual(path.name, '.env')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', guarded):
            code, output = self.cli(FIXTURES / 'good/recursive', '--json')
        self.assertEqual(code, 0)
        self.assertNotIn('RECURSION_AUDIT_ENV_MARKER_DO_NOT_READ', output)

    def test_symlinks(self):
        root = self.make_tree()
        with tempfile.TemporaryDirectory() as outside:
            path = Path(outside) / 'source.py'
            path.write_text('os.walk(".")')
            (root / 'linked.py').symlink_to(path)
            (root / 'linked_dir').symlink_to(outside, target_is_directory=True)
            self.assertEqual(audit(root)['findings'][0]['severity'], 'HIGH')
            self.assertEqual(audit(root)['findings'][0]['evidence'], [])

    def test_exclusions(self):
        root = self.make_tree('top-level only')
        for directory in ['docs', 'examples']:
            (root / directory).mkdir()
            (root / directory / 'walk.py').write_text('os.walk(".")')
        self.assertEqual(len(audit(root)['verified_claims']), 1)

    def test_docs_nested(self):
        root = self.make_tree('A tool.')
        (root / 'docs/nested').mkdir(parents=True)
        (root / 'docs/nested/guide.md').write_text('scans recursively')
        self.assertEqual(len(audit(root)['findings']), 1)

    def test_other_markdown_excluded(self):
        root = self.make_tree('A tool.')
        (root / 'OTHER.md').write_text('scans recursively')
        self.assertEqual(audit(root)['findings'], [])

    def test_parse_diagnostic(self):
        root = self.make_tree(source='def bad(')
        self.assertEqual(len(audit(root)['errors']), 1)

    def test_version(self):
        with self.assertRaises(SystemExit) as error:
            code, output = self.cli('--version')
        self.assertEqual(error.exception.code, 0)
        result = subprocess.run([sys.executable, '-m', 'recursion_claim_audit', '--version'], capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), '0.1.0')

    def test_usage(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            main(['--unknown'])
        self.assertEqual(error.exception.code, 1)

    def test_missing_target(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            main(['/no/such/audit/tree'])
        self.assertEqual(error.exception.code, 1)

    def test_self_audit(self):
        result = audit(Path(__file__).resolve().parents[1])
        self.assertEqual(result['findings'], [])
        self.assertEqual(result['verified_claims'], [])


if __name__ == '__main__':
    unittest.main()
