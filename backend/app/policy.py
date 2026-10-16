import copy
import fnmatch
import json
import os
import re
from pathlib import Path
from .listing_access import load_listing_access, is_listing_command
from .command_boundary import checked_path, command_boundary, EXECUTION_TOOLS, protected_parts
from .content_guard import inspect_read

DEFAULT_POLICY = {
    "version": 1,
    "default_action": "block",
    "ultra_security": False,
    "note": "Policy engine. default_action is used when no rule matches. "
            "Hard workspace/credential boundaries and command eligibility run before allow/ask rules.",
    "rules": [
        {
            "id": "deny-sensitive-gemini-credentials",
            "enabled": True,
            "action": "block",
            "reason": "Access to CLI credentials and global configuration is strictly blocked.",
            "path_re": r"(?i).*[\\/]\.gemini[\\/](oauth_creds\.json|config[\\/]hooks\.json)$",
            "tools": [],
        },
        {
            "id": "allow-cli-builtin-skills",
            "enabled": True,
            "action": "allow",
            "reason": "Allow read-only access to CLI built-in skills and documentation.",
            "builtin_skills": True,
            "tools": ["view_file", "read_file"],
        },
        {
            "id": "cmd-deny-blocklist",
            "enabled": True,
            "action": "block",
            "reason": "Command blocked by AgentGuard policy (matches blocked pattern).",
            "command_re": r"(?i)(rm\s+-rf|format\s+|cipher\s+/w|net\s+user|reg\s+delete|del\s+/[a-z]*[fsq].*\\|Remove-Item\s+-Recurse\s+-Force\s+[A-Z]:\\\\|Get-Content\s+.*win\.ini)",
            "tools": ["run_command"],
        },
        {
            "id": "cmd-allow-example",
            "enabled": False,
            "action": "allow",
            "reason": "Example: allowlist of safe commands (substring match).",
            "command": "git status",
            "tools": ["run_command"],
        },
        {
            "id": "review-workspace-operations",
            "enabled": True,
            "action": "ask",
            "reason": "Validated workspace operation requires your approval.",
            "tools": ["view_file", "read_file", "list_dir", "grep_search", "find_by_name",
                      "search_files", "write_to_file", "create_file", "replace_file_content",
                      "multi_replace_file_content", "edit_file", "sed_file", "notebook_edit",
                      "delete_file", "remove_file", "run_command"],
        },
    ],
}

FILE_TOOLS = {
    "view_file",
    "write_to_file",
    "delete_file",
    "remove_file",
    "replace_file_content",
    "multi_replace_file_content",
    "sed_file",
    "edit_file",
    "read_file",
    "list_dir",
    "grep_search",
    "find_by_name",
    "search_files",
    "list_resources",
    "read_resource",
    "notebook_edit",
    "delete_knowledge",
    "create_file",
    "execute_browser_javascript",
}


def is_deletion_operation(tool: str, args: dict) -> bool:
    if tool in ('delete_file', 'remove_file'):
        return True
    if tool in EXECUTION_TOOLS or tool == 'run_command':
        command = str(args.get('CommandLine') or args.get('command') or '').strip()
        tokens = command.split()
        if tokens and tokens[0].lower() in ('remove-item', 'del', 'rm'):
            return True
    return False

PATH_KEYS = (
    "AbsolutePath",
    "FilePath",
    "TargetFile",
    "target_file",
    "File",
    "file",
    "Path",
    "path",
    "Root",
    "root",
    "Directory",
    "directory",
    "Cwd",
    "cwd",
    "WorkingDirectory",
    "working_directory",
    "file_path",
    "dir_path",
    "notebook_path",
)


def normalize_path(p: str) -> str:
    try:
        return os.path.normcase(os.path.realpath(os.path.abspath(p)))
    except Exception:
        return os.path.normcase(os.path.abspath(p))


def extract_path(tool: str, args: dict) -> str | None:
    for key in PATH_KEYS:
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def is_within(child: str, parent: str) -> bool:
    c = normalize_path(child)
    p = normalize_path(parent)
    if c == p:
        return True
    return c.startswith(p.rstrip("\\/") + os.sep)


class PolicyEngine:
    def __init__(self, data_dir: Path, workspace: Path):
        self.data_dir = data_dir
        self.workspace = workspace
        self.builtin_skills = Path.home() / ".gemini" / "antigravity-cli" / "builtin" / "skills"
        self.policy_file = data_dir / "policy.json"
        self.data = self._load()

    def _load(self) -> dict:
        if self.policy_file.exists():
            try:
                return json.loads(self.policy_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        data = copy.deepcopy(DEFAULT_POLICY)
        self._save(data)
        return data

    def _save(self, data: dict):
        self.policy_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def set_policy(self, data: dict):
        if data.get("default_action") not in ("allow", "block", "ask"):
            raise ValueError("default_action must be allow, block or ask")
        if not isinstance(data.get("rules"), list):
            raise ValueError("rules must be a list")
        for rule in data["rules"]:
            if not isinstance(rule, dict) or rule.get("action") not in ("allow", "block", "ask"):
                raise ValueError("Every rule needs a valid action")
            if not isinstance(rule.get("tools", []), list) or not all(isinstance(t, str) for t in rule.get("tools", [])):
                raise ValueError("Rule tools must be a list of strings")
            if "builtin_skills" in rule and not isinstance(rule["builtin_skills"], bool):
                raise ValueError("builtin_skills must be a boolean")
            for key in ("command_re", "path_re"):
                if rule.get(key):
                    try:
                        re.compile(rule[key])
                    except (re.error, TypeError) as exc:
                        raise ValueError(f"Invalid {key}: {exc}") from exc
        if "ultra_security" in data and not isinstance(data["ultra_security"], bool):
            raise ValueError("ultra_security must be a boolean")
        self._save(data)
        self.data = data

    def get_policy(self) -> dict:
        return self.data

    def dry_run(self, tool: str, args: dict) -> dict:
        decision, reason, rule_id = self.evaluate(tool, args)
        return {
            "tool": tool,
            "args": args,
            "decision": decision,
            "reason": reason,
            "rule_id": rule_id,
            "workspace": str(self.workspace),
        }

    def _match_rule(self, rule: dict, tool: str, args: dict) -> bool:
        # Also constrain the old regex rule when loading an existing policy.
        if rule.get("builtin_skills") or rule.get("id") == "allow-cli-builtin-skills":
            if not self._is_builtin_skill_read(tool, args):
                return False
        tools = rule.get("tools") or []
        if tools and not any(fnmatch.fnmatchcase(tool, t) for t in tools):
            return False
        name = rule.get("name")
        if name and name != tool:
            return False
        cmd = str(args.get("CommandLine") or args.get("command") or "")
        sub = rule.get("command")
        if sub and sub not in cmd:
            return False
        cre = rule.get("command_re")
        if cre:
            try:
                if not re.search(cre, cmd):
                    return False
            except re.error:
                return False
        path = extract_path(tool, args) or ""
        pre = rule.get("path_re")
        if pre:
            try:
                if not re.search(pre, path):
                    return False
            except re.error:
                return False
        return True

    def _is_builtin_skill_read(self, tool: str, args: dict) -> bool:
        if tool not in ("view_file", "read_file"):
            return False
        paths = [value.strip() for key, value in args.items()
                 if key in PATH_KEYS and isinstance(value, str) and value.strip()]
        if not paths:
            return False
        # Compare real targets against the installed location, not a resolved
        # root that could itself be redirected by a junction.
        root = os.path.normcase(os.path.abspath(self.builtin_skills))
        try:
            for value in paths:
                path = Path(value)
                if not path.is_absolute():
                    return False
                target = path.resolve(strict=True)
                resolved = os.path.normcase(str(target))
                if not target.is_file() or os.path.commonpath([resolved, root]) != root:
                    return False
                if target.stat().st_nlink > 1 or protected_parts(Path(os.path.relpath(resolved, root)).parts):
                    return False
            return True
        except (OSError, ValueError, RuntimeError):
            return False

    def evaluate(self, tool: str, args: dict, *, broker_validated: bool = False):
        if not isinstance(tool, str) or not tool:
            return 'block', 'A recognized tool name is required.', '__unsupported_tool'
        if not isinstance(args, dict):
            return 'block', 'Tool arguments must be an object.', '__invalid_arguments'
        if tool == 'manage_task' and str(args.get('Action', '')).lower() == 'send_input':
            return 'block', 'Sending input to an existing shell bypasses command validation.', '__command_boundary'
        if tool == 'http_request':
            if not broker_validated:
                return 'block', 'Network access requires the validated allowlisted HTTP broker.', '__network_boundary'
        elif tool not in FILE_TOOLS | EXECUTION_TOOLS or tool == 'execute_browser_javascript':
            return 'block', 'Tool is not supported by the AgentGuard policy gate; execution is blocked.', '__unsupported_tool'
        if bool(self.data.get("ultra_security", False)) and is_deletion_operation(tool, args):
            return 'block', 'Destructive file deletion is prohibited in Ultra Security mode.', '__ultra_security'
        listing_allowed = False
        if tool == 'run_command':
            command = str(args.get('CommandLine') or args.get('command') or '')
            access = load_listing_access(self.data_dir, self.workspace)
            if access and 'list-workspace.cmd' in command.lower():
                cwd = args.get('Cwd')
                if (not is_listing_command(command, access) or not isinstance(cwd, str)
                        or not os.path.isabs(cwd) or not is_within(cwd, str(self.workspace))
                        or any(args.get(key) for key in ('BypassSandbox', 'IsDaemon', 'RunPersistent', 'RequestedTerminalID'))):
                    return 'block', 'The listing helper requires its exact command and a workspace working directory.', '__listing_boundary'
                listing_allowed = True
        if tool in EXECUTION_TOOLS and not listing_allowed:
            reason = command_boundary(self.workspace, args)
            if reason:
                return 'block', reason, '__command_boundary'
        if tool in FILE_TOOLS and not self._is_builtin_skill_read(tool, args):
            values = [value for key, value in args.items() if key in PATH_KEYS]
            if not values:
                return 'block', 'A recognized literal target path is required.', '__workspace_containment'
            try:
                cwd = self.workspace
                for key in ('Cwd', 'cwd', 'WorkingDirectory', 'working_directory'):
                    if key in args:
                        cwd = checked_path(self.workspace, args[key])
                for value in values:
                    checked_path(self.workspace, value, cwd=cwd)
            except (ValueError, TypeError, OSError, RuntimeError) as exc:
                return 'block', str(exc), '__workspace_containment'
        if not self._is_builtin_skill_read(tool, args):
            try:
                content_reason = inspect_read(self.workspace, tool, args)
            except (OSError, ValueError, TypeError, RuntimeError):
                return 'block', 'Source content inspection failed; the read is blocked.', '__content_inspection'
            if content_reason:
                return 'block', content_reason, '__content_inspection'
        rules = self.data.get("rules") or []
        for rule in rules:
            if not rule.get("enabled", True):
                continue
            action = rule.get("action")
            if action not in ("allow", "block", "ask"):
                continue
            if self._match_rule(rule, tool, args):
                return action, rule.get("reason") or "Matched policy rule", rule.get("id", "rule")
        path = extract_path(tool, args)
        resolved = str(self.workspace / path) if path and not os.path.isabs(path) else path
        if resolved and tool in FILE_TOOLS and not is_within(resolved, str(self.workspace)):
            return "block", f"Path outside approved workspace: {path}", "__workspace_containment"
        if is_deletion_operation(tool, args):
            if self.data.get("default_action") == "block":
                return 'block', 'Default policy action', '__default'
            return 'ask', 'Workspace file deletion requires user approval.', '__workspace_file_delete'
        default = self.data.get("default_action", "block")
        return default, ("No matching policy rule permits or offers review for this action."
                         if default == 'block' else "Default policy action"), "__default"
