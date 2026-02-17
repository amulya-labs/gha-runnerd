#!/usr/bin/env python3
"""
Bash command validator for Claude Code PreToolUse hook.
Reads patterns from TOML config and validates commands.

Source: https://github.com/amulya-labs/claude-agents
License: MIT (https://opensource.org/licenses/MIT)
"""

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Python 3.11+ has tomllib built-in
try:
    import tomllib
except ImportError:
    # Fallback for Python < 3.11
    try:
        import tomli as tomllib
    except ImportError:
        print(
            "Error: Python 3.11+ required, or install 'tomli' package for older versions",
            file=sys.stderr,
        )
        sys.exit(1)


@dataclass
class CompiledPattern:
    """A pre-compiled regex pattern with metadata."""
    regex: re.Pattern
    section: str
    original: str


def load_config(config_path: str) -> dict:
    """Load and validate TOML configuration."""
    try:
        with open(config_path, "rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        print(f"Error: Invalid TOML in {config_path}: {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)


def compile_patterns(config: dict, category: str) -> list[CompiledPattern]:
    """Extract and compile patterns for a category (deny/ask/allow).

    Pre-compiling regex patterns improves performance significantly
    when validating many commands.
    """
    compiled = []
    for section_name, section in config.get(category, {}).items():
        if isinstance(section, dict) and "patterns" in section:
            for pattern in section["patterns"]:
                try:
                    regex = re.compile(pattern)
                    compiled.append(CompiledPattern(
                        regex=regex,
                        section=f"{category}.{section_name}",
                        original=pattern
                    ))
                except re.error as e:
                    print(f"Warning: Invalid regex '{pattern}' in {category}.{section_name}: {e}",
                          file=sys.stderr)
    return compiled


def strip_env_vars(cmd: str) -> str:
    """Strip environment variable assignments from command start.

    Handles: VAR=value, VAR="value", VAR='value', VAR=$(cmd), VAR=$VAR
    """
    while True:
        cmd = cmd.lstrip()
        match = re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', cmd)
        if not match:
            break

        rest = cmd[match.end():]

        if rest.startswith('$('):
            # Command substitution $(...)
            depth = 1
            i = 2
            while depth > 0 and i < len(rest):
                if rest[i] == '(':
                    depth += 1
                elif rest[i] == ')':
                    depth -= 1
                i += 1
            cmd = rest[i:]
        elif rest.startswith('`'):
            # Backtick substitution
            end = rest.find('`', 1)
            cmd = rest[end + 1:] if end > 0 else ""
        elif rest.startswith('"'):
            # Double-quoted value
            i = 1
            while i < len(rest):
                if rest[i] == '\\' and i + 1 < len(rest):
                    i += 2
                    continue
                if rest[i] == '"':
                    break
                i += 1
            cmd = rest[i + 1:]
        elif rest.startswith("'"):
            # Single-quoted value
            end = rest.find("'", 1)
            cmd = rest[end + 1:] if end > 0 else ""
        elif rest.startswith('$') and len(rest) > 1 and re.match(r'[A-Za-z_]', rest[1]):
            # Variable reference $VAR
            var_match = re.match(r'^\$[A-Za-z_][A-Za-z0-9_]*', rest)
            cmd = rest[var_match.end():] if var_match else rest
        else:
            # Unquoted value - ends at whitespace
            val_match = re.match(r'^[^\s]*\s*', rest)
            cmd = rest[val_match.end():] if val_match else ""

    return cmd.lstrip()


def strip_leading_comment(cmd: str) -> str:
    """Strip shell comments from the start of a command.

    Handles multi-line commands where the first line is a comment.
    """
    lines = cmd.split('\n')
    while lines and lines[0].strip().startswith('#'):
        lines.pop(0)
    return '\n'.join(lines).lstrip()


def split_commands(cmd: str) -> list[str]:
    """Split command on &&, ||, ; (respecting quotes, comments, and shell syntax).

    Special handling for:
    - ;; (case statement terminator) - not a split point
    - Quoted strings
    """
    segments = []
    current = ""
    quote = None
    i = 0

    while i < len(cmd):
        char = cmd[i]

        # Track quotes (ignore escaped by odd number of backslashes)
        if char in ('"', "'"):
            backslash_count = 0
            j = i - 1
            while j >= 0 and cmd[j] == '\\':
                backslash_count += 1
                j -= 1
            if backslash_count % 2 == 0:
                if quote is None:
                    quote = char
                elif quote == char:
                    quote = None

        # Split on && || ; outside quotes
        if quote is None:
            if cmd[i:i+2] in ('&&', '||'):
                if current.strip():
                    segments.append(current)
                current = ""
                i += 2
                continue
            elif char == ';':
                # Don't split on ;; (case statement terminator)
                if cmd[i:i+2] == ';;':
                    current += ';;'
                    i += 2
                    continue
                if current.strip():
                    segments.append(current)
                current = ""
                i += 1
                continue

        current += char
        i += 1

    if current.strip():
        segments.append(current)

    return segments


# Shell control flow keywords that may prefix body commands
# These keywords introduce blocks but the body commands need separate validation
CONTROL_FLOW_KEYWORDS = re.compile(
    r'^(then|else|elif|do)\s+',
    re.IGNORECASE
)

# Shell control flow terminators that may have redirections attached
# These complete control structures and are safe on their own
CONTROL_FLOW_TERMINATORS = re.compile(
    r'^(done|fi|esac)(\s*[<>|&].*)?$',
    re.IGNORECASE
)


def strip_control_flow_keyword(segment: str) -> str:
    """Strip shell control flow keywords from segment start.

    When commands like 'if condition; then body; fi' are split on ';',
    we get segments like 'then body'. This function strips the 'then '
    prefix so 'body' can be validated independently.

    For terminators like 'done < file.txt', we return empty string since
    the redirection is part of the loop construct, not a separate command.

    Returns the segment with any leading control flow keyword removed,
    or empty string for terminators (which are inherently safe).
    """
    # Check for terminators first (done, fi, esac) - possibly with redirection
    if CONTROL_FLOW_TERMINATORS.match(segment):
        return ""

    # Check for body-introducing keywords (then, else, do, etc.)
    match = CONTROL_FLOW_KEYWORDS.match(segment)
    if match:
        return segment[match.end():].lstrip()

    return segment


def clean_segment(segment: str) -> str:
    """Clean a command segment: strip whitespace, subshell chars, env vars, comments."""
    segment = segment.strip()

    # Strip leading comments
    segment = strip_leading_comment(segment)

    # Strip leading subshell/grouping: ( {
    while segment and segment[0] in '({':
        segment = segment[1:].lstrip()

    # Strip trailing subshell/grouping: ) }
    while segment and segment[-1] in ')}':
        segment = segment[:-1].rstrip()

    # Strip env vars
    segment = strip_env_vars(segment)

    # Strip shell control flow keywords (then, else, do, etc.)
    # This allows validation of the body command within control structures
    segment = strip_control_flow_keyword(segment)

    return segment


def check_patterns(segment: str, patterns: list[CompiledPattern]) -> tuple[bool, str]:
    """Check if segment matches any compiled pattern.

    Returns (matched, section_name).
    """
    for pattern in patterns:
        if pattern.regex.search(segment):
            return True, pattern.section
    return False, ""


def output_decision(decision: str, reason: str):
    """Output JSON decision for Claude Code hook."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason
        }
    }))


def validate_command(
    command: str,
    deny_patterns: list[CompiledPattern],
    ask_patterns: list[CompiledPattern],
    allow_patterns: list[CompiledPattern]
) -> tuple[str, str]:
    """Validate a command against patterns.

    Returns (decision, reason) tuple.
    Decision is one of: "deny", "ask", "allow"
    """
    # First, check DENY patterns against the FULL command (before splitting)
    # This catches dangerous chaining patterns like "; rm -rf /" or "&& sudo"
    matched, section = check_patterns(command, deny_patterns)
    if matched:
        return "deny", f"Blocked: '{command[:100]}' matches {section}"

    # Split into segments
    segments = split_commands(command)

    final_decision = "allow"
    final_reason = "Command matches allow patterns"

    for segment in segments:
        cleaned = clean_segment(segment)
        if not cleaned:
            continue

        # Check DENY first (per-segment)
        matched, section = check_patterns(cleaned, deny_patterns)
        if matched:
            return "deny", f"Blocked: '{cleaned}' matches {section}"

        # Check ASK
        matched, section = check_patterns(cleaned, ask_patterns)
        if matched:
            if final_decision != "ask":
                final_decision = "ask"
                final_reason = f"'{cleaned}' matches {section}"
            continue

        # Check ALLOW
        matched, _ = check_patterns(cleaned, allow_patterns)
        if matched:
            continue

        # Not in any list - mark as ask (default behavior)
        if final_decision != "ask":
            final_decision = "ask"
            final_reason = f"'{cleaned}' not in auto-approve list"

    return final_decision, final_reason


def main():
    if len(sys.argv) != 2:
        print("Usage: validate-bash.py <config.toml>", file=sys.stderr)
        sys.exit(1)

    config_path = sys.argv[1]
    config = load_config(config_path)

    # Compile patterns once at startup (improves performance)
    deny_patterns = compile_patterns(config, "deny")
    ask_patterns = compile_patterns(config, "ask")
    allow_patterns = compile_patterns(config, "allow")

    # Read JSON input from stdin
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        # Invalid input, let it pass
        sys.exit(0)

    command = input_data.get("tool_input", {}).get("command", "")
    if not command:
        sys.exit(0)

    decision, reason = validate_command(
        command, deny_patterns, ask_patterns, allow_patterns
    )

    output_decision(decision, reason)


if __name__ == "__main__":
    main()
