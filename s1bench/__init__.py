"""S1Bench: how well System One models control multi-step browser tasks, and when to stop trusting them."""

import os

# browser_harness reads these once, when it is first imported. Python runs this file before any
# s1bench submodule, so every import path through the bench sets them in time.
# Assign, never setdefault: an exported BU_NAME would otherwise aim the bench at your real Chrome.
os.environ["BU_NAME"] = "s1bench"
os.environ["BH_TAB_MARKER"] = "0"
os.environ["BH_TELEMETRY"] = "0"
