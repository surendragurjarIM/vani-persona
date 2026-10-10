"""Build the uploadable Sarvam code tool: template + the lexicon from live/lexicon.py, in one file.

    python -m sarvam_agent.build_switch_tool   ->  sarvam_agent/update_persona_mode.py
"""
import pprint
from pathlib import Path

from live.lexicon import SIGNAL_PATTERNS

HERE = Path(__file__).parent
OUT = HERE / "update_persona_mode.py"


def build() -> Path:
    tpl = (HERE / "switch_tool_template.py").read_text(encoding="utf-8")
    block = "SIGNAL_PATTERNS = " + pprint.pformat(SIGNAL_PATTERNS, width=110, sort_dicts=False)
    OUT.write_text(tpl.replace("# @@SIGNAL_PATTERNS@@", block), encoding="utf-8")
    return OUT


if __name__ == "__main__":
    print(build())
