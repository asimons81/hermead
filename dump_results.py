"""Full dump of HermeAd smoke test results."""
import sys
sys.path.insert(0, r"C:\Users\asimo\projects\hermead")

from hermead.hooks import post_tool_call, _file_type, _is_ignored
from hermead.config import find_project_root, load_hermead_config
from hermead.detector import detect_tooling
from hermead.reporter import format_full, format_structured
from pathlib import Path

test_file = r"C:\Users\asimo\projects\hermead\test_smoke.py"

# Clear previous results
post_tool_call._last_results = []
post_tool_call._last_structured = {}

# Call the hook fresh
post_tool_call(
    tool_name="write_file",
    result={"bytes_written": 454, "resolved_path": test_file},
    kwargs={"path": test_file},
)

results = getattr(post_tool_call, "_last_results", [])

print(f"Total findings: {len(results)}")
print()

for i, r in enumerate(results):
    print(f"--- Finding {i+1} ---")
    for k, v in r.items():
        print(f"  {k}: {v}")
    print()

# Full formatted report
print("=" * 60)
print("FULL FORMATTED REPORT")
print("=" * 60)
print(format_full(results))
