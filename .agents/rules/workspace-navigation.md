# Workspace Directory Navigation and Surfing Rule

## Directive
When discovering, surfing, or listing directories and files in the workspace, ALWAYS perform the inspection in a SINGLE command. NEVER execute sequential one-by-one commands across subfolders.

## AgentGuard Policy Boundaries
AgentGuard enforces strict command validation. Attempting unsupported syntax causes command denials and triggers inefficient multi-command fallbacks:
- **BLOCKED syntax**:
  - Aliases and utilities: `ls`, `dir`, `tree`, `find`.
  - Wildcards and expansions: `*`, `?`, `$()`.
  - Shell chaining and arbitrary pipelines: `;`, `&&`, `|` (except strictly `| Select-Object Name`).
  - Unbounded recursion: `Get-ChildItem -Recurse` without both `-Directory` and `-Depth 0..3`.
- **ALLOWED syntax**:
  - Literal `Get-ChildItem`, `Get-Content`, `Get-Location`, `pwd`.
  - Validated metadata commands are automatically granted under `__workspace_metadata` without approval prompts.

## Optimal Single-Command Surfing Patterns

1. **Recursive Subfolder Surfing (up to depth 3)**:
   Always combine `-Directory` with an explicit `-Depth` (0 to 3) and optional `-Name`:
   ```powershell
   Get-ChildItem -Path <folder> -Directory -Depth 2 -Name
   ```
   *Example (inspecting all folders in `ps01-tests` in 1 single command)*:
   ```powershell
   Get-ChildItem -Path ps01-tests -Directory -Depth 2 -Name
   ```
   *(or with approved projection)*:
   ```powershell
   Get-ChildItem -Path ps01-tests -Directory -Depth 2 | Select-Object Name
   ```

2. **Workspace Root Folder Tree**:
   ```powershell
   Get-ChildItem -Directory -Depth 2 -Name
   ```

3. **Immediate Directory Contents**:
   ```powershell
   Get-ChildItem -Path <folder> -Name
   ```

4. **Immediate Subdirectories Only**:
   ```powershell
   Get-ChildItem -Path <folder> -Directory -Name
   ```

## Rules to Enforce
- NEVER run sequential commands to check directories one-by-one.
- ALWAYS supply `-Directory` when using `-Depth` or `-Recurse`.
- NEVER combine `-Directory` and `-File`.
- Keep `-Depth` between 0 and 3.
