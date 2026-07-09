"""
Facade re-export of the product's MaxTool classes for the AI agent toolkits.

Kept out of api.py so light consumers (e.g. sharing) don't pull the LLM tool
stack, and because importing max_tools from api.py created a circular import:
max_tools -> invite_email -> logic -> facade.contracts triggered
facade/__init__ -> api -> max_tools while max_tools was still initializing.
"""

from products.user_interviews.backend.max_tools import AnalyzeUserInterviewsTool, CreateUserInterviewTopicTool

__all__ = [
    "AnalyzeUserInterviewsTool",
    "CreateUserInterviewTopicTool",
]
