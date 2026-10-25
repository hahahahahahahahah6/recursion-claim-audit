"""Command line interface."""
import argparse
import json
from pathlib import Path
from . import __version__
from .audit import audit


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(__import__('sys').stderr)
        self.exit(1, self.prog + ': error: ' + message + '\n')


def main(argv=None):
    parser = Parser(description='Audit documented directory traversal depth against Python source.')
    parser.add_argument('path', nargs='?', default='.')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--ignore', action='append', default=[], metavar='GLOB')
    parser.add_argument('--fail-on', choices=['MEDIUM', 'HIGH'], default='MEDIUM')
    parser.add_argument('--version', action='version', version=__version__)
    args = parser.parse_args(argv)
    if not Path(args.path).is_dir():
        parser.error('path must be an existing directory')
    result = audit(args.path, args.ignore)
    failed = any(f['severity'] == 'HIGH' or args.fail_on == 'MEDIUM' for f in result['findings'])
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print('FAIL' if failed else 'PASS')
        for finding in result['findings']:
            print(finding['severity'] + ' ' + finding['rule'])
            for claim in finding['claims']:
                print('  {path}:{line}: {text}'.format(**claim))
            for evidence in finding['evidence']:
                print('  ' + json.dumps(evidence, sort_keys=True))
        if args.verbose:
            print(json.dumps(dict(verified_claims=result['verified_claims'], errors=result['errors']), indent=2))
    return 2 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
