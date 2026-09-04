import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from env_contract_kit import parse_env, rules_from, validate, main

class ContractTests(unittest.TestCase):
    def test_quotes_export_comments(self):
        self.assertEqual(parse_env('export A="x # y" # note\nB=a#b\nC=v # note'),
                         {'A': 'x # y', 'B': 'a#b', 'C': 'v'})
    def test_duplicate_rejected(self):
        with self.assertRaisesRegex(ValueError, 'line 2'):
            parse_env('A=1\nA=2')
    def test_malformed_does_not_echo_value(self):
        with self.assertRaises(ValueError) as cm:
            parse_env('A="secret')
        self.assertNotIn('secret', str(cm.exception))
    def test_numeric_bounds_and_types(self):
        rules = rules_from('[vars.PORT]\ntype="integer"\nmin=1\nmax=65535')
        self.assertEqual(validate({'PORT': '80'}, rules), [])
        self.assertEqual(validate({'PORT': '0'}, rules)[0]['code'], 'below_min')
        self.assertEqual(validate({'PORT': '1.5'}, rules)[0]['code'], 'invalid_type')
    def test_nonfinite(self):
        for value in ['NaN', 'Infinity']:
            self.assertEqual(validate({'A': value}, {'A': {'type': 'number'}})[0]['code'], 'invalid_type')
    def test_missing_extra_optional_empty(self):
        rules = {'A': {}, 'B': {'required': False}, 'C': {'allow_empty': True}}
        self.assertEqual(validate({'C': '', 'D': 'private'}, rules),
                         [{'key': 'A', 'code': 'missing'}, {'key': 'D', 'code': 'unexpected'}])
    def test_boolean_url_enum(self):
        self.assertEqual(validate({'A': 'TRUE', 'B': 'https://example.org/a'},
                                 {'A': {'type': 'boolean'}, 'B': {'type': 'url'}}), [])
        self.assertEqual(validate({'A': 'x'}, {'A': {'enum': ['y']}})[0]['code'], 'not_in_enum')
    def test_bad_contracts(self):
        for text in ['x=1', '[vars.A]\ntype="wrong"', '[vars.A]\nrequired="yes"',
                     '[vars.A]\ntype="number"\nmin=2\nmax=1', '[vars.A]\nsecret="foo"']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                rules_from(text)
    def test_cli_error_and_redaction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'rules').write_text('[vars.A]\ntype="integer"')
            (root/'env').write_text('A=TOP_SECRET')
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main([str(root/'rules'), str(root/'env')]), 1)
            self.assertNotIn('TOP_SECRET', out.getvalue())
    def test_bad_path(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['does-not-exist', 'missing']), 2)
