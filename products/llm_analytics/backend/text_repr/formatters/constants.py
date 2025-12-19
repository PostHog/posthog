"""
Shared constants for text representation formatters.

Centralizes all magic numbers and configuration values for consistent behavior
across message, tool, text, trace, and span formatters.
"""

# Truncation and display limits
DEFAULT_TRUNCATE_BUFFER = 1000  # Characters to show at start/end when truncating
MAX_UNPARSED_DISPLAY_LENGTH = 500  # Max length for unparsed content display
MAX_UNABLE_TO_PARSE_REPR_LENGTH = 500  # Max length for repr() fallback in error messages

# Uniform sampling for large text representations
# GPT-4.1-mini has 1M token context, but char-to-token ratio varies widely:
# - Simple English text: ~4 chars/token
# - JSON/code/special chars: ~2-3 chars/token (much worse)
# Using 2M chars to safely fit within context even with poor token efficiency.
# At worst case 2:1 ratio: 2M chars = 1M tokens (leaves minimal buffer for prompt/output)
# At typical 2.5:1 ratio: 2M chars = 800K tokens (leaves 200K buffer)
DEFAULT_MAX_LENGTH = 2_000_000
PRESERVE_HEADER_LINES = 5  # Number of header lines to always keep when sampling
SAMPLED_VIEW_HEADER = (
    "[SAMPLED VIEW: Showing ~{percent:.0f}% of {total:,} lines. Gaps in line numbers indicate omitted content.]"
)
# Iterative sampling refinement: initial estimate uses average line length, but sampled
# lines may be longer. These control convergence to fit within max_length.
SAMPLING_MAX_ITERATIONS = 10  # Max refinement iterations (typically converges in 2-3)
SAMPLING_REDUCTION_FACTOR = 0.9  # Safety margin when reducing target line count

# Tool formatting
DEFAULT_TOOLS_COLLAPSE_THRESHOLD = 5  # Collapse tool lists longer than this

# Tree rendering
MAX_TREE_DEPTH = 10  # Maximum depth for hierarchical trace tree rendering

# Visual formatting
SEPARATOR = "-" * 80  # Horizontal separator line for sections
