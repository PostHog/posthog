"""
Shared constants for text representation formatters.

Centralizes all magic numbers and configuration values for consistent behavior
across message, tool, text, trace, and span formatters.
"""

# Truncation and display limits
DEFAULT_TRUNCATE_BUFFER = 1000  # Characters to show at start/end when truncating
MAX_UNPARSED_DISPLAY_LENGTH = 500  # Max length for unparsed content display
MAX_UNABLE_TO_PARSE_REPR_LENGTH = 500  # Max length for repr() fallback in error messages

# Tool formatting
DEFAULT_TOOLS_COLLAPSE_THRESHOLD = 5  # Collapse tool lists longer than this

# Tree rendering
MAX_TREE_DEPTH = 10  # Maximum depth for hierarchical trace tree rendering
