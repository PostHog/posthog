"""Detection signals guessed from a warehouse source type's name, for the types nobody has curated.

Projects usually name a vendor's credentials after the vendor: `ZENDESK_API_TOKEN`,
`QUICKBOOKS_CLIENT_ID`. So every uncurated type gets one `.env` key prefix built from its
name, in both the split and the joined spelling (`^(QUICK_BOOKS|QUICKBOOKS)_`). A curated
entry in `curated.py` replaces the derived one.
"""

import re
from collections.abc import Set

from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
from products.wizard.backend.tool_catalog.types import Tool, ToolOrigin, ToolSignals, WizardSetupMode

# A shorter prefix, such as `BOX_` or `HEX_`, shows up in too many unrelated projects.
MIN_NAME_LENGTH = 4

# Source names that are also common words. Their prefix (`BRANCH_`, `MERGE_`, `CUSTOM_`) says
# nothing about the vendor, so these types need a curated entry to be detected at all.
GENERIC_NAMES: frozenset[str] = frozenset(
    {
        "Adjust",
        "Aha",
        "Allegro",
        "Anvil",
        "Apollo",
        "Arcade",
        "Astronomer",
        "Attentive",
        "Autumn",
        "Aviator",
        "Beamer",
        "Boulevard",
        "Branch",
        "Buffer",
        "Calibre",
        "Campfire",
        "Captivate",
        "Chameleon",
        "Chorus",
        "Clarify",
        "Classy",
        "Clay",
        "Clever",
        "Clip",
        "Clover",
        "Concord",
        "Cortex",
        "Crisp",
        "Cursor",
        "Curve",
        "Custom",
        "Decagon",
        "Deputy",
        "EConomic",
        "Embrace",
        "Factorial",
        "Folk",
        "Framer",
        "Fred",
        "Frill",
        "Fulcrum",
        "Gem",
        "Guardian",
        "Guru",
        "Harvest",
        "Harvey",
        "Hex",
        "Impact",
        "Insightful",
        "Instantly",
        "Intruder",
        "Jellyfish",
        "Jobber",
        "Kernel",
        "Kick",
        "Klaus",
        "Latitude",
        "Lattice",
        "Lever",
        "Liana",
        "Mantle",
        "Mention",
        "Mercury",
        "Merge",
        "Metronome",
        "Mode",
        "Mono",
        "Motion",
        "Nutshell",
        "Orbit",
        "Outlook",
        "Outreach",
        "Perigon",
        "Perk",
        "Pocket",
        "Podium",
        "Polygon",
        "Poplar",
        "Preset",
        "Productive",
        "Profound",
        "Quay",
        "Quo",
        "Recreation",
        "Reverb",
        "Schematic",
        "Scrunch",
        "Sim",
        "Singular",
        "Slash",
        "Sleuth",
        "Sprig",
        "Swan",
        "Tana",
        "Teamwork",
        "Tempo",
        "Ternary",
        "Timely",
        "Toast",
        "Transistor",
        "Twenty",
        "Vantage",
        "Virtuous",
        "Windmill",
        "Wiz",
        "Zero",
    }
)

_WORD_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def env_key_pattern(source_name: str) -> str | None:
    split = _WORD_BOUNDARY.sub("_", source_name).upper()
    joined = split.replace("_", "")
    if len(joined) < MIN_NAME_LENGTH or source_name in GENERIC_NAMES:
        return None
    if split == joined:
        return f"^{joined}_"
    return f"^({split}|{joined})_"


def derived_tools(curated_kinds: Set[str]) -> tuple[Tool, ...]:
    tools = []
    for source_type in sorted(ExternalDataSourceType, key=lambda member: member.value):
        if source_type.value in curated_kinds:
            continue
        pattern = env_key_pattern(source_type.value)
        if pattern is None:
            continue
        tools.append(
            Tool(
                kind=source_type.value,
                label=source_type.label,
                origin=ToolOrigin.DERIVED,
                signals=ToolSignals(packages={}, env_key_patterns=(pattern,), script_hosts=()),
                warehouse_source_type=source_type,
                # The new-source form works for every source type, so an uncurated one never
                # assumes a credential the terminal can collect.
                wizard_setup_mode=WizardSetupMode.DEEP_LINK,
                competes_with=(),
                llm=False,
                superseded_by=(),
            )
        )
    return tuple(tools)
