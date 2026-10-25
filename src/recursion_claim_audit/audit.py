"""Offline documentation and directory-descent analysis."""
import ast
import fnmatch
import re
from pathlib import Path

RECURSIVE = ('recursively', 'recursive scan', 'recursive search', 'recursively scans',
             'scans recursively', 'searches recursively', 'recursively searches',
             'walks the tree', 'walks the directory tree', 'recursive traversal',
             'traverses recursively', 'recursively walks', 'descends into subdirectories',
             'all subdirectories', 'including subdirectories', 'nested directories')
SHALLOW_NEG = ('not recursive', 'does not recurse', "doesn't recurse", 'no recursion',
               'without recursion', 'does not descend', "doesn't descend")
SHALLOW = ('top-level only', 'top level only', 'non-recursive', 'single directory',
           'shallow scan', 'flat scan') + SHALLOW_NEG
NEGATION = re.compile(r"\b(?:no|not|never|without|doesn't|don't|isn't)\b", re.I)


def contains(sentence, phrase):
    return re.search(r'(?<![\w-])' + re.escape(phrase) + r'(?![\w-])', sentence, re.I) is not None


def extract_claims(text, path='README.md'):
    claims = []
    fence = None
    paragraph = []

    def flush():
        if not paragraph:
            return
        joined = ' '.join(line for _, line in paragraph)
        offsets = []
        for number, line in paragraph:
            offsets.extend([number] * (len(line) + 1))
        for match in re.finditer(r'.+?(?:[.!?](?=\s|$)|$)', joined):
            sentence = match.group().strip()
            negated = bool(NEGATION.search(sentence))
            for family, phrases in [('recursive', RECURSIVE), ('shallow', SHALLOW)]:
                hits = [p for p in phrases if contains(sentence, p)
                        and (not negated or (family == 'shallow' and p in SHALLOW_NEG))]
                if hits:
                    start = match.start() + len(match.group()) - len(match.group().lstrip())
                    claims.append(dict(family=family, path=path, line=offsets[start],
                                       text=sentence))
        paragraph.clear()

    for number, line in enumerate(text.splitlines(), 1):
        mark = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if mark:
            token = mark.group(1)
            if fence is None:
                flush()
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        if fence:
            continue
        if not line.strip():
            flush()
        else:
            paragraph.append((number, line))
    flush()
    return claims


def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return dotted(node.value) + '.' + node.attr
    return ''


def extract_evidence(source, path):
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        return [], str(exc)
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name] = item.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for item in node.names:
                aliases[item.asname or item.name] = node.module + '.' + item.name

    def name(call):
        parts = dotted(call.func).split('.')
        return '.'.join([aliases.get(parts[0], parts[0])] + parts[1:])

    items = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            target = name(node)
            attr = node.func.attr if isinstance(node.func, ast.Attribute) else None
            kind = None
            if target in ('os.walk', 'os.path.walk'):
                kind = target
            elif attr == 'rglob':
                kind = 'rglob'
            elif target == 'glob.glob' and any(k.arg == 'recursive' and
                    isinstance(k.value, ast.Constant) and k.value.value is True for k in node.keywords):
                kind = 'recursive-glob'
            elif (target == 'glob.glob' or attr == 'glob') and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str) and '**' in node.args[0].value:
                kind = 'glob-pattern'
            if kind:
                items.add((node.lineno, kind))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Nested definitions are separate scopes, not part of this reader.
            def body_nodes(root):
                for child in ast.iter_child_nodes(root):
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                        continue
                    yield child
                    yield from body_nodes(child)
            calls = [n for n in body_nodes(node) if isinstance(n, ast.Call)]
            self_call = any(isinstance(c.func, ast.Name) and c.func.id == node.name for c in calls)
            reader = any(name(c) in ('os.listdir', 'os.scandir') or
                         (isinstance(c.func, ast.Attribute) and c.func.attr == 'iterdir') for c in calls)
            if self_call and reader:
                items.add((node.lineno, 'self-recursive-reader'))
    return [dict(path=path, line=line, kind=kind) for line, kind in sorted(items)], None


def audit(root, ignore=()):
    root = Path(root)
    claims, production, testonly, errors = [], [], [], []
    source_count = 0
    # Do not follow directory symlinks, or open non-source files (including .env).
    import os
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(directory) / d).is_symlink()
                         and d not in ('.git', '__pycache__', '.venv', 'venv', 'build', 'dist')
                         and not any(fnmatch.fnmatch((Path(directory) / d).relative_to(root).as_posix(), p) for p in ignore))
        for filename in sorted(files):
            file = Path(directory) / filename
            relative = file.relative_to(root).as_posix()
            if file.is_symlink() or any(fnmatch.fnmatch(relative, p) for p in ignore):
                continue
            parts = file.relative_to(root).parts
            is_doc = relative == 'README.md' or (parts[0] == 'docs' and file.suffix == '.md')
            is_test = any(p in ('tests', 'fixtures') for p in parts[:-1]) or filename.startswith('test_') or filename.endswith('_test.py')
            is_source = file.suffix == '.py' and not any(p in ('docs', 'examples') for p in parts[:-1])
            if not (is_doc or is_source):
                continue
            if is_source and not is_test:
                source_count += 1
            try:
                text = file.read_text(encoding='utf-8')
            except (OSError, UnicodeError) as exc:
                errors.append(dict(path=relative, error=str(exc)))
                continue
            if is_doc:
                claims.extend(extract_claims(text, relative))
            if is_source:
                evidence, error = extract_evidence(text, relative)
                (testonly if is_test else production).extend(evidence)
                if error:
                    errors.append(dict(path=relative, error=error))
    findings, verified = [], []
    for family in ('recursive', 'shallow'):
        family_claims = [c for c in claims if c['family'] == family]
        if not family_claims:
            continue
        severity, evidence, suffix = None, [], ''
        if not source_count:
            severity, evidence = 'HIGH', [dict(kind='no-source')]
        elif family == 'recursive' and not production:
            severity, evidence = ('MEDIUM', testonly) if testonly else ('HIGH', [])
            suffix = '-test-only' if testonly else ''
        elif family == 'shallow' and (production or testonly):
            severity, evidence = ('HIGH', production) if production else ('MEDIUM', testonly)
            suffix = '' if production else '-test-only'
        if severity:
            findings.append(dict(rule='documented-' + family + '-claim-false' + suffix,
                                 severity=severity, claims=family_claims, evidence=evidence))
        else:
            verified.append(dict(family=family, claims=family_claims, evidence=production if family == 'recursive' else []))
    return dict(findings=findings, verified_claims=verified, errors=errors)
