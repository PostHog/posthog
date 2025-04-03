import json
import os

from src.properties import CAMPAIGN_PROPERTIES, CORE_FILTER_DEFINITIONS_BY_GROUP

script_dir = os.path.dirname(os.path.abspath(__file__))
output_dir = os.path.join(script_dir, "dist")


def generate_python_constants():
    py_output = "from typing import Literal, NotRequired, TypedDict\n\n"

    py_output += "class CoreFilterDefinition(TypedDict):\n"
    py_output += "   label: str\n"
    py_output += "   description: NotRequired[str]\n"
    py_output += "   examples: NotRequired[list[str | int | float]]\n"
    py_output += "   system: NotRequired[bool]\n"
    py_output += '   type: NotRequired[Literal["String", "Numeric", "DateTime", "Boolean"]]\n'
    py_output += "   ignored_in_assistant: NotRequired[bool]\n\n"

    py_output += "CAMPAIGN_PROPERTIES = " + json.dumps(CAMPAIGN_PROPERTIES) + "\n\n"
    py_output += "CORE_FILTER_DEFINITIONS_BY_GROUP: dict[str, dict[str, CoreFilterDefinition]] = {\n"

    for group, definitions in CORE_FILTER_DEFINITIONS_BY_GROUP.items():
        py_output += f'    "{group}": {{\n'
        for def_key, definition in definitions.items():
            py_output += f'        "{def_key}": {{\n'
            for key, value in definition.items():
                if isinstance(value, str):
                    py_output += f'            "{key}": {repr(value)},\n'
                else:
                    py_output += f'            "{key}": {value},\n'
            py_output += "        },\n"
        py_output += "    },\n"

    py_output += "}\n"

    with open(os.path.join(output_dir, "python", "taxonomy.py"), "w") as f:
        f.write(py_output)


def generate_typescript_constants():
    ts_output = "export const CORE_FILTER_DEFINITIONS_BY_GROUP = {\n"

    for group, definitions in CORE_FILTER_DEFINITIONS_BY_GROUP.items():
        ts_output += f"    {group}: {{\n"
        for def_key, definition in definitions.items():
            # Handle empty string keys and keys with spaces
            if def_key == "" or " " in def_key:
                key_str = f"'{def_key}'"
            else:
                key_str = def_key

            ts_output += f"        {key_str}: {{\n"
            for key, value in definition.items():
                if key == "ignored_in_assistant" or key == "system":
                    continue
                if isinstance(value, str):
                    # Handle multiline strings and escape apostrophes
                    value_escaped = value.replace("'", "\\'").replace("\n", "\\n")
                    ts_output += f"            {key}: '{value_escaped}',\n"
                elif isinstance(value, bool):
                    # Convert Python True/False to JavaScript true/false
                    ts_output += f"            {key}: {str(value).lower()},\n"
                else:
                    ts_output += f"            {key}: {value},\n"
            ts_output += "        },\n"
        ts_output += "    },\n"

    ts_output += "};\n\n"
    ts_output += "export const PROPERTY_KEYS = Object.keys(CORE_FILTER_DEFINITIONS_BY_GROUP.event_properties);\n"

    with open(os.path.join(output_dir, "typescript", "taxonomy.ts"), "w") as f:
        f.write(ts_output)


generate_python_constants()
generate_typescript_constants()
