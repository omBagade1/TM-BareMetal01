"""Launch a no-op worker to check setup; does not certify full containment."""
import json
import sys
from app import config
from app.windows_sandbox import WindowsSandbox


def main():
    runner = WindowsSandbox(config.WORKSPACE_DIR)
    try:
        result = runner.execute('__probe', {})
    except Exception as exc:
        result = {'ok': False, 'error_type': type(exc).__name__, 'reason': str(exc)}
    print(json.dumps({'workspace': str(config.WORKSPACE_DIR), **result}, indent=2))
    if result.get('ok'):
        print('Worker startup succeeded. Network, ACL and resource attack tests are still required.')
    return 0 if result.get('ok') else 1


if __name__ == '__main__':
    sys.exit(main())
