"""Validate fixtures, optionally evaluate policy. Never execute candidate tools."""
import argparse
import http.client
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evaluate', action='store_true', help='Dry policy checks against the running local backend')
    parser.add_argument('--port', type=int, default=8912)
    args = parser.parse_args()
    suite = Path(__file__).resolve().parent
    workspace = suite.parent
    manifest = json.loads((suite / 'cases.json').read_text(encoding='utf-8'))
    cases = manifest['cases']
    assert len({c['id'] for c in cases}) == len(cases), 'Duplicate case IDs'
    assert sum(c['kind'] == 'normal' for c in cases) == 5
    assert sum(c['kind'] == 'attack' for c in cases) == 8
    for case in cases:
        folder = (suite / case['folder']).resolve()
        assert folder.is_relative_to(suite), 'Case path escapes suite'
        assert (folder / 'README.md').is_file(), f'Missing instructions: {case["id"]}'
        assert case['expected_policy'], f'Missing expectation: {case["id"]}'
    print('Fixture manifest valid: 5 normal tasks, 8 attacks. No tools executed.')
    if not args.evaluate:
        return 0

    def expand(value):
        if isinstance(value, str):
            return value.replace('{workspace}', str(workspace)).replace('{outside}', str(workspace.parent))
        if isinstance(value, dict):
            return {k: expand(v) for k, v in value.items()}
        return value

    failures = 0
    # HTTPConnection does not follow redirects. Destination is fixed loopback.
    for case in cases:
        for index, candidate in enumerate([case, *case.get('variants', [])]):
            connection = http.client.HTTPConnection('127.0.0.1', args.port, timeout=10)
            name = case['id'] + (f'.variant-{index}' if index else '')
            try:
                payload = {'tool': candidate['tool'], 'args': expand(candidate['args'])}
                connection.request('POST', '/api/policy/evaluate', json.dumps(payload),
                                   {'Content-Type': 'application/json', 'Origin': f'http://127.0.0.1:{args.port}'})
                response = connection.getresponse()
                data = json.loads(response.read().decode('utf-8'))
                if response.status != 200:
                    raise ValueError(f'HTTP {response.status}: {data}')
                decision = data.get('decision')
                matches = decision in candidate['expected_policy']
                failures += not matches
                print(f'{name}: {"MATCH" if matches else "MISMATCH"} policy={decision}; {data.get("reason", "")}')
            except (OSError, ValueError, http.client.HTTPException) as exc:
                failures += 1
                print(f'{name}: ERROR {exc}')
            finally:
                connection.close()
    print(f'Policy-only check: {failures} mismatch/error(s). No live execution, network containment, or audit evidence established.')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
