"""
Facade for user_interviews product.

This module provides the public interface for other products to interact with user interviews.
"""

from ..contracts import IntervieweeIdentity
from .api import has_replied, parse_interviewee_identifier

__all__ = [
    "IntervieweeIdentity",
    "has_replied",
    "parse_interviewee_identifier",
]
