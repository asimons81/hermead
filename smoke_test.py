"""HermeAd smoke test: simulate post_tool_call to verify hook pipeline works.

This simulates what Hermes does after a write_file call when the plugin
is loaded. If tooling (ruff, mypy, bandit) is available, their findings
will be returned and formatted.
"""
import sys
import os
from pathlib import Path

# Ensure hermead is importable
sys.path.insert(0, r"C:\Users\asimo\projects\hermead")

from hermead.hooks import post_tool_call
from hermead.reporter import format_full, format_structured
from hermead.config import find_project_root, load_hermead_config
from hermead.detector import detect_tooling

# The test file we wrote
test_file = r"C:\Users\asimo\projects\hermead\test_smoke.py"

print("=" * 60)
print("HermeAd Smoke Test — Hook Simulation")
print("=" * 60)

# 1. Check project root detection
project_root = find_project_root(Path(test_file))
print(f"\n[1] Project root: {project_root}")

# 2. Check file type detection
from hermead.hooks import _file_type
ftype = _file_type(test_file)
print(f"[2] File type: {ftype}")

# 3. Check config loading
config = load_hermead_config(project_root)
print(f"[3] Config keys: {list(config.keys())}")

# 4. Check tooling detection
detected = detect_tooling(project_root)
print(f"[4] Detected tooling: {detected.get('python', {})}")

# 5. Call post_tool_call directly (simulating Hermes after write_file)
print(f"\n[5] Calling post_tool_call('write_file', result, {{'path': test_file}})...")
print("    (This runs ruff, mypy, bandit on the test file)")
sys.stdout.flush()

post_tool_call(
    tool_name="write_file",
    result={"bytes_written": 454, "resolved_path": test_file},
    kwargs={"path": test_file},
)

# 6. Check what was found
results = getattr(post_tool_call, "_last_results", None)
structured = getattr(post_tool_call, "_last_structured", None)

print(f"\n[6] Results count: {len(results) if results else 0}")

if results:
    # List tool categories found
    tools_used = set(r.get("tool", "?") for r in results)
    print(f"    Tools that ran: {', '.join(sorted(tools_used))}")
    print(f"    Total findings: {len(results)}")

    # Severity breakdown
    from collections import Counter
    sev_counts = Counter(r.get("severity", "?") for r in results)
    for sev, count in sorted(sev_counts.items()):
        print(f"    {sev}: {count}")

    # Show formatted report
    print(f"\n[7] Formatted report:")
    report = format_full(results)
    print(report)

    # Show structured (JSON) output
    print(f"\n[8] Structured output ({len(structured)} entries):")
    for entry in structured[:5]:
        print(f"    {entry.get('tool','?')}: {entry.get('severity','?')} - {entry.get('message','?')[:100]}")
else:
    print("    No results — check tool availability (ruff, mypy, bandit)")

print("\n" + "=" * 60)
print("Smoke test complete.")
print("=" * 60)
