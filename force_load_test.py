"""Force-reload hermead plugin in the current session and test the hook."""
import sys
sys.path.insert(0, r"C:\Users\asimo\projects\hermead")

# Import the plugin manager and force discovery
from hermes_cli.plugins import discover_plugins, has_hook, get_plugin_manager, invoke_hook
from hermes_cli.plugins import get_plugin_manager as get_pm

print("=== HermeAd Live Hook Test ===")
print()

# Step 1: Check current state
pm = get_pm()
before_hooks = pm._hooks.get("post_tool_call", [])
print(f"Before reload: post_tool_call callbacks = {len(before_hooks)}")

# Step 2: Force rediscover
print("\nForcing plugin rediscovery...")
discover_plugins(force=True)

# Step 3: Check state after reload
pm2 = get_pm()
after_hooks = pm2._hooks.get("post_tool_call", [])
print(f"After reload:  post_tool_call callbacks = {len(after_hooks)}")
for cb in after_hooks:
    print(f"  Callback: {cb.__name__} ({type(cb).__name__})")

# Step 4: Check if hermead is loaded
print("\nLoaded plugins:")
for key, loaded in sorted(pm2._plugins.items()):
    if "hermead" in key.lower():
        print(f"  {key}: enabled={loaded.enabled}, hooks={len(loaded.hooks_registered)}, error={loaded.error}")

# Step 5: Invoke the hook directly
print("\nInvoking post_tool_call hook for test_smoke.py...")
results = invoke_hook(
    "post_tool_call",
    tool_name="write_file",
    result={"bytes_written": 454, "resolved_path": r"C:\Users\asimo\projects\hermead\test_smoke.py"},
    kwargs={"path": r"C:\Users\asimo\projects\hermead\test_smoke.py"},
)
print(f"Hook returned: {results}")
