from enum import StrEnum


class SlackFeature(StrEnum):
    THREAD_FOLLOWUP = "thread_followup"
    SUBSCRIPTION = "subscription"
    CODE_CHANGE_PR = "code_change_pr"
    MCP_TOOL = "mcp_tool"
    DIRECT_MESSAGE = "direct_message"
    FILE_ATTACHMENTS = "file_attachments"
    FILE_OUTPUTS = "file_outputs"
    INBOX_CHANNEL = "inbox_channel"
    PROJECT_IN_MENTION = "project_in_mention"
    APP_HOME_PROJECT = "app_home_project"
    MODEL_IN_MENTION = "model_in_mention"
    AUTO_MODEL_CHOICE = "auto_model_choice"
    APP_HOME_TASKS = "app_home_tasks"
    INSIGHT_UNFURL = "insight_unfurl"
    FORK_THREAD = "fork_thread"
    UNPROMPTED_ANSWERS = "unprompted_answers"
    ANSWER_RATING = "answer_rating"
    REPLY_SUGGESTIONS = "reply_suggestions"
