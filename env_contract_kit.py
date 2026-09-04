"""Validate a deliberately small dotenv dialect against a typed TOML contract."""
import argparse
import json
import re
import sys
import tomllib
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
TYPES = {"string", "integer", "number", "boolean", "url"}

def parse_env(text):
    values = {}
    for line_no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].lstrip()
        key, sep, value = line.partition('=')
        key, value = key.strip(), value.strip()
        if not sep or not KEY.fullmatch(key):
            raise ValueError(f'invalid assignment at line {line_no}')
        if key in values:
            raise ValueError(f'duplicate key at line {line_no}')
        if value.startswith(('"', "'")):
            quote = value[0]
            end = value.find(quote, 1)
            if end < 0 or (value[end + 1:].strip() and not value[end + 1:].strip().startswith('#')):
                raise ValueError(f'invalid quoted value at line {line_no}')
            value = value[1:end]
        else:
            value = re.split(r'\s+#', value, maxsplit=1)[0].rstrip()
        values[key] = value
    return values

def rules_from(text):
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        raise ValueError('invalid TOML contract') from None
    if set(doc) != {'vars'} or not isinstance(doc['vars'], dict) or not doc['vars']:
        raise ValueError('contract must contain a nonempty [vars] table')
    for key, rule in doc['vars'].items():
        if not KEY.fullmatch(key) or not isinstance(rule, dict):
            raise ValueError('invalid variable rule')
        if set(rule) - {'type', 'required', 'allow_empty', 'enum', 'min', 'max'}:
            raise ValueError('unknown rule option')
        if not isinstance(rule.get('type', 'string'), str) or rule.get('type', 'string') not in TYPES:
            raise ValueError('unsupported type')
        for flag in ('required', 'allow_empty'):
            if flag in rule and type(rule[flag]) is not bool:
                raise ValueError('rule flags must be boolean')
        if 'enum' in rule and (not isinstance(rule['enum'], list) or not rule['enum'] or
                               not all(isinstance(v, str) for v in rule['enum'])):
            raise ValueError('enum must be a nonempty list of strings')
        for bound in ('min', 'max'):
            if bound in rule:
                if rule.get('type') not in {'integer', 'number'}:
                    raise ValueError('bounds require a numeric type')
                if type(rule[bound]) not in (int, float) or not Decimal(str(rule[bound])).is_finite():
                    raise ValueError('bounds must be finite numbers')
        if 'min' in rule and 'max' in rule and rule['min'] > rule['max']:
            raise ValueError('min exceeds max')
    return doc['vars']

def validate(values, rules, allow_extra=False):
    findings = []
    for key, rule in sorted(rules.items()):
        def add(code):
            findings.append({'key': key, 'code': code})
        if key not in values:
            if rule.get('required', True):
                add('missing')
            continue
        value = values[key]
        if not value:
            if not rule.get('allow_empty', False):
                add('empty')
            continue
        kind = rule.get('type', 'string')
        try:
            if kind == 'integer' and not re.fullmatch(r'[+-]?[0-9]+', value):
                raise ValueError()
            if kind in {'integer', 'number'}:
                number = Decimal(value)
                if not number.is_finite():
                    raise ValueError()
                for bound, op in [('min', lambda a, b: a < b), ('max', lambda a, b: a > b)]:
                    if bound in rule and op(number, Decimal(str(rule[bound]))):
                        add('below_min' if bound == 'min' else 'above_max')
            if kind == 'boolean' and value.lower() not in {'true', 'false'}:
                raise ValueError()
            if kind == 'url':
                url = urlsplit(value)
                if url.scheme not in {'http', 'https'} or not url.hostname or any(c.isspace() for c in value):
                    raise ValueError()
                _ = url.port
        except (ValueError, InvalidOperation):
            add('invalid_type')
        if 'enum' in rule and value not in rule['enum']:
            add('not_in_enum')
    if not allow_extra:
        findings.extend({'key': k, 'code': 'unexpected'} for k in sorted(values.keys() - rules.keys()))
    return findings

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('contract', type=Path)
    parser.add_argument('env', type=Path)
    parser.add_argument('--allow-extra', action='store_true')
    args = parser.parse_args(argv)
    try:
        rules = rules_from(args.contract.read_text(encoding='utf-8-sig'))
        values = parse_env(args.env.read_text(encoding='utf-8-sig'))
        findings = validate(values, rules, args.allow_extra)
        print(json.dumps({'findings': findings, 'checked': len(rules)}, indent=2))
        return int(bool(findings))
    except (OSError, UnicodeError):
        print('error: cannot read UTF-8 input', file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
