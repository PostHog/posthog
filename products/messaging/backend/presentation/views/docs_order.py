from enum import IntEnum


# Read by `sort_operations` in posthog/api/documentation.py to order these viewsets in the API reference.
class MessagingDocsOrder(IntEnum):
    SEND = 1
    EMAILS = 2
    ATTACHMENTS = 3
    PREFERENCES = 4
