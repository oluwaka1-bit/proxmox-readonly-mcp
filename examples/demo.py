from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from portfolio_pve import MockAPI, ToolRegistry

tools = ToolRegistry(MockAPI())
print(json.dumps({"tools": tools.describe(),
                  "guests": tools.invoke("list_guests", role="viewer"),
                  "backups": tools.invoke("backup_history", {"limit": 1}, role="viewer")}, indent=2))
