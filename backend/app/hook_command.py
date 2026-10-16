"""Build a hook command that survives the CLI's Windows shell invocation."""
import base64
import os
import shlex
from pathlib import Path


def build_hook_command(python: str, hook: Path) -> str:
    if os.name != "nt":
        return shlex.join([python, "-X", "utf8", str(hook)])

    def literal(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    # cmd.exe and subprocess argv quoting do not agree on embedded double quotes.
    # Keep the outer command quote-free; PowerShell receives only a base64 script.
    # Explicitly forward stdin because native pipeline input otherwise varies by host.
    script = (
        "$ErrorActionPreference = 'Stop'; "
        "$OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
        "[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false); "
        "$hookPayload = [Console]::In.ReadToEnd(); "
        f"$hookPayload | & {literal(python)} -X utf8 {literal(str(hook))}; "
        "exit $LASTEXITCODE"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return f"powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand {encoded}"
