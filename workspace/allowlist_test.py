import urllib.request
import urllib.error
import socket
import ssl
import time

# Change these to match your configured network allowlist.
TESTS = [
    {
        "name": "Approved domain",
        "url": "https://example.com/",
        "should_succeed": True,
    },
    {
        "name": "Unapproved domain",
        "url": "https://example.org/",
        "should_succeed": False,
    },
]


def check_https(url):
    try:
        request = urllib.request.Request(
            url,
            method="GET",
            headers={"User-Agent": "AgentSandbox-Test/1.0"},
        )

        context = ssl.create_default_context()

        with urllib.request.urlopen(
            request, timeout=8, context=context
        ) as response:
            return True, f"HTTP status {response.status}"

    except urllib.error.HTTPError as exc:
        # An HTTP response means the server was reachable.
        return True, f"Server responded with HTTP {exc.code}"

    except (
        urllib.error.URLError,
        socket.timeout,
        TimeoutError,
        OSError,
    ) as exc:
        return False, str(exc)


def main():
    passed = 0

    print("=== Agent Sandbox: HTTPS Allowlist Test ===")

    for test in TESTS:
        start = time.time()
        reachable, reason = check_https(test["url"])
        duration = time.time() - start

        expected = test["should_succeed"]
        success = reachable == expected

        if success:
            passed += 1

        print(f"\nTest: {test['name']}")
        print(f"URL: {test['url']}")
        print(f"Expected: {'ALLOW' if expected else 'BLOCK'}")
        print(f"Actual: {'REACHABLE' if reachable else 'UNREACHABLE'}")
        print(f"Details: {reason}")
        print(f"Duration: {duration:.2f}s")
        print(f"Result: {'PASS' if success else 'FAIL'}")

    print(f"\nSummary: {passed}/{len(TESTS)} tests passed")


if __name__ == "__main__":
    main()
