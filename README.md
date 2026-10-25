# recursion-claim-audit

Audit documented directory traversal depth against Python source.

Version 0.1.0. A stdlib-only, offline static auditor for Python projects.
It executes no audited code, uses no network, skips symlinks, and never reads
`.env` contents. Only root `README.md`, Markdown files beneath `docs/`, and
eligible Python source are opened. Files outside the target are not opened.

## Usage

Requires Python 3.9 or newer. Install and run:

```sh
python3 -m pip install .
recursion-claim-audit /path/to/project
python3 -m recursion_claim_audit /path/to/project --json
recursion-claim-audit . --verbose --ignore 'vendor/*' --fail-on HIGH
recursion-claim-audit --version
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m build
```

The target defaults to the current directory. `--ignore GLOB` is repeatable
and matches relative paths; matching directories are pruned. `--verbose`
adds verified claims and source diagnostics to text output. `--json` emits
an object with `findings`, `verified_claims`, and `errors`. Findings include
rule, severity, claims (path, line, text, family), and evidence (path, line,
kind). Parse/read errors appear in diagnostics and do not themselves create
rules. Exit status is 0 for PASS, 2 for findings meeting the threshold, and
1 for usage errors. The default threshold is MEDIUM; `--fail-on HIGH` keeps
MEDIUM findings visible while permitting exit 0.

## Claim extraction

Claims come only from root README.md and docs Markdown. Fenced blocks are
excluded; inline code counts as prose. Matching is case-insensitive and uses
only the exact phrases below, with word boundaries. The families are
independent; contradictory documentation can produce separate findings.

```text
RECURSIVE:
recursively
recursive scan
recursive search
recursively scans
scans recursively
searches recursively
recursively searches
walks the tree
walks the directory tree
recursive traversal
traverses recursively
recursively walks
descends into subdirectories
all subdirectories
including subdirectories
nested directories

SHALLOW:
top-level only
top level only
non-recursive
not recursive
single directory
does not recurse
doesn't recurse
no recursion
without recursion
shallow scan
flat scan
does not descend
doesn't descend
```

Negation is asymmetric: a sentence containing no, not, never, without,
doesn't, don't, or isn't suppresses the RECURSIVE family. SHALLOW phrases
which express negation themselves still count; other SHALLOW phrases are
suppressed in negated sentences. This includes the two descent-negation
phrases at the end of the list. Sentence boundaries are punctuation or
paragraph boundaries. The bare adverb in the first family counts on its
own, while the bare noun “recursion” does not. For example:

```text
walks recursively                  -> recursive claim
recursion support                  -> no claim
does not scan recursively          -> no claim
this tool is not recursive         -> shallow claim
does not scan top-level only       -> no claim
```

## Rules

One finding per claimed family; repeated prose is retained in its claims.

| Rule | Severity | Condition |
| --- | --- | --- |
| documented-recursive-claim-false | HIGH | RECURSIVE claim without production or test evidence |
| documented-recursive-claim-false-test-only | MEDIUM | RECURSIVE claim with test evidence alone |
| documented-shallow-claim-false | HIGH | SHALLOW claim with production evidence |
| documented-shallow-claim-false-test-only | MEDIUM | SHALLOW claim with test evidence alone |

A claimed family with no production Python source always gets its base HIGH
rule with `no-source` evidence. A RECURSIVE claim with production evidence
is verified. A SHALLOW claim without evidence anywhere is verified. No
claim means PASS regardless of source evidence.

## Named evidence

Each call site or definition is one item, deduplicated by file, line, kind.

| Kind | Recognized syntax |
| --- | --- |
| os.walk | Standard library call, including per-file imported aliases |
| os.path.walk | Legacy standard library call |
| rglob | Attribute call on any receiver |
| recursive-glob | glob.glob with literal True for its recursive keyword |
| glob-pattern | glob.glob or any .glob with a literal first argument containing ** |
| self-recursive-reader | Function calls its own name and reads directory entries via os.listdir, os.scandir or .iterdir |

Production excludes tests/ and fixtures/ directories, test_*.py, *_test.py,
docs/, and examples/. Test and fixture source is collected separately.
Symlinked files and directories are skipped. Build outputs, virtual
environments, Git metadata and bytecode directories are skipped too.

## Differentiation

| Neighbour | Scope compared with this tool |
| --- | --- |
| sort-claim-audit | Output order rather than traversal depth |
| pagination-claim-audit | Result paging rather than local descent |
| instruction-drift | Instruction-file truth rather than traversal behaviour |
| streaming-claim-audit | Read chunking rather than tree depth |
| bandit / ruff | Code issues rather than documented promises |
| os.walk / pathlib documentation | Primitive semantics rather than docs-versus-code truth |

## Honest limitations

Exact-phrase matching misses paraphrases and does not resolve which API a
sentence describes. Evidence is a deliberate over-approximation: dead code
counts, and presence does not prove the promised operation reaches that
code. Receiver types are not inferred for attribute matches. Imported names
are tracked per file, without resolving shadowing, control flow or dynamic
imports. Nested function definitions are treated separately.

A directory-entry read alone (os.listdir, os.scandir, or .iterdir) is not
evidence. Repeating a read over a fixed list of directories is not evidence.
glob.glob without the keyword or the double-star pattern is not evidence;
a plain Path.glob pattern is not evidence either. A function calling itself
without directory reads is not evidence. A directory reader without a
self-call or a recognized walker is not evidence. Third-party walkers such
as pathspec, wcmatch and the scandir package are outside scope. A keyword
named recursive with literal True on a non-glob call is not evidence.
Syntax and decoding errors are reported without executing fallback code.
The tool cannot prove runtime coverage or filesystem permissions.
