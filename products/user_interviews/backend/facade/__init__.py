"""
Facade for user_interviews product.

This module provides the public interface for other products to interact with user interviews.
"""

from .api import has_replied, parse_interviewee_identifier
from .contracts import IntervieweeIdentity

__all__ = [
    "IntervieweeIdentity",
    "has_replied",
    "parse_interviewee_identifier",
]
