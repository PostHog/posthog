import os
import json
import requests
import uuid
import sys
import time
import threading
import shutil  # noqa: F401
import re
import readline  # noqa: F401
import logging
import traceback  # noqa: F401
from typing import Any, Dict  # noqa: F401, UP035
from config import API_KEY, API_ENDPOINT, MODEL

try:
    import anthropic
    from flask import Flask, request, jsonify, session  # noqa: F401
    from flask_cors import CORS
except ImportError as e:
    print(f"Error importing required packages: {e}")  # noqa: T201
    print("Please ensure you have installed: anthropic flask flask-cors")  # noqa: T201
    sys.exit(1)

from max_search_tool import max_search_tool


class ConversationHistory:
    def __init__(self):
        self.turns = []

    def add_turn_user(self, content):
        self.turns.append({"role": "user", "content": [{"type": "text", "text": content}]})

    def add_turn_assistant(self, content):
        if isinstance(content, list):
            self.turns.append({"role": "assistant", "content": content})
        else:
            self.turns.append({"role": "assistant", "content": [{"type": "text", "text": content}]})

    def get_turns(self):
        return self.turns


class RequestCounter:
    def __init__(self):
        self._lock = threading.Lock()
        self._count = 0

    def increment(self) -> int:
        with self._lock:
            self._count += 1
            return self._count


request_counter = RequestCounter()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

client = anthropic.Anthropic()

app = Flask(__name__)
CORS(app)
CORS(
    app,
    resources={
        r"/chat": {"origins": ["http://localhost:8000"], "methods": ["POST"], "allow_headers": ["Content-Type"]}
    },
)

conversation_histories = {}

search_log_handler = logging.StreamHandler()
search_log_handler.setLevel(logging.INFO)


def create_simulated_429_response():
    mock_response = requests.Response()
    mock_response.status_code = 429
    mock_response._content = json.dumps(
        {
            "content": "🫣 Uh-oh, I'm really popular today! I've hit my rate limit. I need to catch my breath, please try asking your question again after 30 seconds. 🦔"
        }
    ).encode()
    mock_response.headers["retry-after"] = "1"
    mock_response.headers["anthropic-ratelimit-requests-remaining"] = "0"
    mock_response.headers["anthropic-ratelimit-tokens-remaining"] = "0"
    return mock_response


def should_simulate_rate_limit(count: int) -> bool:
    """Determines if we should simulate a rate limit based on environment variable and request count."""
    simulate_enabled = os.getenv("SIMULATE_RATE_LIMIT", "false").lower() == "true"
    return simulate_enabled and count > 3


def track_cache_performance(response):
    """Track and log cache performance metrics."""
    if "usage" in response:
        usage = response["usage"]
        print(f"Cache creation tokens: {usage.get('cache_creation_input_tokens', 0)}")  # noqa: T201
        print(f"Cache read tokens: {usage.get('cache_read_input_tokens', 0)}")  # noqa: T201
        print(f"Total input tokens: {usage.get('input_tokens', 0)}")  # noqa: T201
        print(f"Total output tokens: {usage.get('output_tokens', 0)}")  # noqa: T201
    else:
        print("No usage information available in the response.")  # noqa: T201


def get_message_content(message):
    if not message or "content" not in message:
        return ""

    content = message["content"]
    if isinstance(content, list):
        for block in content:
            if block.get("type") == "text":
                return block.get("text", "")
            elif block.get("type") == "tool_use":
                return block.get("input", {}).get("query", "")
    elif isinstance(content, str):
        return content
    return ""


def send_message(system_prompt, messages, tools):
    headers = {
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "prompt-caching-2024-07-31",
        "content-type": "application/json",
    }
    data = {
        "model": MODEL,
        "max_tokens": 1024,
        "tools": tools,
        "system": [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
        "messages": messages,
    }

    try:
        logger.info("Sending request to Anthropic API.")
        logger.debug(f"Request headers: {headers}")
        logger.debug(f"Request payload: {json.dumps(data, indent=2)}")

        max_retries = 3
        retry_count = 0
        max_backoff = 32  # Maximum backoff in seconds

        while retry_count <= max_retries:
            # Make the request
            req_count = request_counter.increment()

            # Check if we should use the mock for testing - only check the most recent message
            current_message = get_message_content(messages[-1]) if messages else ""
            if "__500__" in current_message:
                response = mock_post(API_ENDPOINT, headers, data)
                logger.info(f"Using mock response for 500 error test (request #{req_count})")
            else:
                response = requests.post(API_ENDPOINT, headers=headers, json=data)

            rate_limits = {
                "requests_remaining": response.headers.get("anthropic-ratelimit-requests-remaining", "not provided"),
                "tokens_remaining": response.headers.get("anthropic-ratelimit-tokens-remaining", "not provided"),
                "retry_after": response.headers.get("retry-after", "not provided"),
            }
            logger.info(
                f"Rate limits - Requests remaining: {rate_limits['requests_remaining']}, "
                f"Tokens remaining: {rate_limits['tokens_remaining']}"
            )

            if response.status_code == 429:
                if retry_count < max_retries:
                    # Try to get retry_after value, fall back to exponential backoff
                    try:
                        retry_after = (
                            int(rate_limits["retry_after"]) if rate_limits["retry_after"] != "not provided" else None
                        )
                    except (ValueError, TypeError):
                        retry_after = None

                    if retry_after is None:
                        retry_after = min(2**retry_count, max_backoff)  # Exponential backoff with upper bound

                    logger.warning(
                        f"Rate limit exceeded. Attempt {retry_count + 1}/{max_retries}. "
                        f"Retrying in {retry_after} seconds..."
                    )
                    time.sleep(retry_after)
                    retry_count += 1
                    continue
                else:
                    logger.error("Max retries exceeded due to rate limiting")
                    return {
                        "content": "🫣 Uh-oh, I'm really popular today! I've hit my rate limit. I need to catch my breath, please try asking your question again after 30 seconds. 🦔",
                        "isRateLimited": True,
                    }

            if response.status_code in [500, 524, 529]:
                logger.info(f"Server error detected: {response.status_code}")
                error_message = (
                    "🫣 Uh-oh. I wasn't able to connect to the Anthropic API (my brain!) Please try sending your message again in about 1 minute?\n\n"
                    "If this message is still recurring after 5 or 10 minutes, there may be info about the trouble available at [status.anthropic.com](https://status.anthropic.com)."
                )

                logger.info(f"Injecting error message: {error_message}")
                return {"content": [{"type": "text", "text": error_message}], "isError": True}

            # For non-429 responses, ensure other error codes raise exceptions
            response.raise_for_status()

            # Parse and log the response
            response_data = response.json()
            logger.info("Received response from Anthropic API.")
            logger.debug(f"Response data: {json.dumps(response_data, indent=2)}")

            # Track cache performance
            track_cache_performance(response_data)

            return response_data

    except requests.RequestException as e:
        logger.error(f"Request to Anthropic API failed: {str(e)}", exc_info=True)
        raise

    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode JSON response from Anthropic API: {str(e)}", exc_info=True)
        raise

    except Exception as e:
        logger.error(f"Unexpected error in send_message: {str(e)}", exc_info=True)
        raise


def extract_reply(text):
    """Extract a reply enclosed in <reply> tags."""
    try:
        logger.info("Extracting reply from text.")
        if not isinstance(text, str):
            raise ValueError(f"Invalid input: Expected a string, got {type(text)}.")

        pattern = r"<reply>(.*?)</reply>"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            extracted_reply = match.group(1)
            logger.debug(f"Extracted reply: {extracted_reply}")
            return extracted_reply
        else:
            logger.info("No <reply> tags found in the text.")
            return None
    except Exception as e:  # noqa: F841
        logger.error("Error extracting reply.", exc_info=True)
        raise


def process_response(response, messages):
    try:
        if "content" in response:
            assistant_response = response["content"]
            logger.info("Processing response content.")

            if isinstance(assistant_response, list):
                # Keep all content blocks together in one message
                messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_response,  # The entire list of content blocks
                    }
                )

                # Handle tool use if present
                for content_block in assistant_response:
                    if content_block["type"] == "tool_use":
                        query = content_block["input"]["query"]
                        logger.info(f"Handling tool invocation with query: {query}")

                        # Perform search and log results
                        search_results = max_search_tool(query)
                        logger.debug(f"Search results: {search_results}")

                        if isinstance(search_results, str):
                            formatted_results_str = search_results
                        else:
                            formatted_results = []
                            for result in search_results:
                                for passage in result["relevant_passages"]:
                                    formatted_results.append(
                                        f"Text: {passage['text']}\n"
                                        f"Heading: {passage['heading']}\n"
                                        f"Source: {result['page_title']}\n"
                                        f"URL: {passage['url']}\n"
                                    )
                            formatted_results_str = "\n".join(formatted_results)

                        logger.debug(f"Formatted search results: {formatted_results_str}")

                        # Append tool result as a content block
                        messages.append(
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "tool_result",
                                        "tool_use_id": content_block["id"],
                                        "content": formatted_results_str,
                                    }
                                ],
                            }
                        )

                        # Call send_message recursively and log errors
                        try:
                            next_response = send_message(system_prompt, messages, [max_search_tool_tool])
                            updated_messages = process_response(next_response, messages)
                            if updated_messages:
                                messages = updated_messages
                        except Exception as e:  # noqa: F841
                            logger.error("Error during recursive send_message call.", exc_info=True)
                            raise
                return messages
            else:
                # Handle string response (should we convert to content block?)
                messages.append({"role": "assistant", "content": [{"type": "text", "text": assistant_response}]})
                return messages
        else:
            logger.warning("No content found in response.")
            return messages
    except Exception as e:  # noqa: F841
        logger.error("Error processing response.", exc_info=True)
        raise


max_search_tool_tool = {
    "name": "max_search_tool",
    "description": (
        "Searches the PostHog documentation at https://posthog.com/docs, "
        "https://posthog.com/tutorials, to find information relevant to the "
        "user's question. The search query should be a question specific to using "
        "and configuring PostHog."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query, in the form of a question, related to PostHog usage and configuration.",
            }
        },
        "cache_control": {"type": "ephemeral"},
        "required": ["query"],
    },
}


def validate_tool_input(input_data):
    """Validate the input for max_search_tool_tool."""
    try:
        if not isinstance(input_data, dict):
            raise ValueError("Input data must be a dictionary.")
        if "query" not in input_data or not input_data["query"].strip():
            raise ValueError("The 'query' field is required and cannot be empty.")
        logger.debug(f"Tool input validation passed: {input_data}")
    except Exception as e:
        logger.error(f"Tool input validation failed: {str(e)}", exc_info=True)
        raise


def format_response(response):
    if "content" in response:
        assistant_response = response["content"]
        if isinstance(assistant_response, list):
            formatted_response = "\n"
            for content_block in assistant_response:
                if content_block["type"] == "text":
                    formatted_response += content_block["text"] + "\n"
            return formatted_response.strip() + "\n"
        else:
            return "\n" + assistant_response + "\n"
    else:
        return "\n\nError: No response from Max.\n\n"


@app.route("/chat", methods=["POST"])
def chat():
    try:
        logger.info("Incoming request to /chat endpoint.")
        data = request.json
        if not data or "message" not in data:
            logger.warning("Invalid request: No 'message' provided.")
            return jsonify({"error": "No message provided"}), 400

        user_input = data["message"]
        logger.info(f"User input received: {user_input}")

        session_id = data.get("session_id", str(uuid.uuid4()))

        if session_id not in conversation_histories:
            conversation_histories[session_id] = ConversationHistory()

        history = conversation_histories[session_id]

        if not user_input.strip():
            history.add_turn_user("Hello!")
            logger.info("No user input. Sending default greeting.")
            result = send_message(system_prompt, history.get_turns(), [max_search_tool_tool])
            if "content" in result:
                logger.debug(f"Greeting response: {result['content']}")
                history.add_turn_assistant(result["content"])
                return jsonify({"content": result["content"]})

        history.add_turn_user(user_input)

        messages = history.get_turns()

        full_response = ""

        # Send message with full history
        result = send_message(system_prompt, messages, [max_search_tool_tool])
        logger.debug(f"Initial response from send_message: {result}")

        while result and "content" in result:
            if result.get("stop_reason") == "tool_use":
                tool_use_block = result["content"][-1]
                logger.info(f"Tool use requested: {tool_use_block}")

                query = tool_use_block["input"]["query"]
                search_results = max_search_tool(query)
                logger.debug(f"Search results for query '{query}': {search_results}")

                formatted_results = "\n".join(
                    [
                        f"Text: {passage['text']}\nHeading: {passage['heading']}\n"
                        f"Source: {result_item['page_title']}\nURL: {passage['url']}\n"
                        for result_item in search_results
                        for passage in result_item["relevant_passages"]
                    ]
                )

                # Append assistant's response with content blocks
                history.add_turn_assistant(result["content"])

                # Append tool result as a content block
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "tool_result", "tool_use_id": tool_use_block["id"], "content": formatted_results}
                        ],
                    }
                )

                for block in result["content"]:
                    if block["type"] == "text":
                        full_response += block["text"] + "\n"

                result = send_message(system_prompt, history.get_turns(), [max_search_tool_tool])
            else:
                if isinstance(result["content"], list):
                    for block in result["content"]:
                        if block["type"] == "text":
                            full_response += block["text"] + "\n"
                    history.add_turn_assistant(result["content"])
                else:
                    full_response += result["content"]
                    history.add_turn_assistant(result["content"])
                break

        logger.info("Response successfully processed.")
        return jsonify({"content": full_response.strip(), "session_id": session_id})

    except requests.RequestException as e:
        logger.error(f"Request to Anthropic API failed: {str(e)}", exc_info=True)
        try:
            # Try to parse the error message as JSON in case it's our custom message
            error_content = json.loads(str(e))
            if "content" in error_content:
                return jsonify(error_content), 429
        except json.JSONDecodeError:
            pass
        # Fall back to generic error handling
        return jsonify({"error": str(e)}), 500


def mock_post(url, headers, json_data):
    # Check if the message contains '__500__'
    if any("__500__" in msg["content"][0]["text"] for msg in json_data["messages"]):
        # Only return 500 error for the first request after seeing __500__
        if not hasattr(mock_post, "has_returned_500"):
            mock_post.has_returned_500 = True
            mock_response = requests.Response()
            mock_response.status_code = 500
            mock_response._content = bytes(
                '{"content": [{"type": "text", "text": "Mocked 500 error"}]}', encoding="utf-8"
            )
            return mock_response
        else:
            # Reset the flag and let the real API handle the response
            delattr(mock_post, "has_returned_500")
            return requests.post(url, headers=headers, json=json_data)

    # For all other requests, use the real API
    return requests.post(url, headers=headers, json=json_data)


if __name__ == "__main__":
    system_prompt = """
    You are Max, the friendly and knowledgeable PostHog Virtual Support AI (you are playing the role of PostHog's mascot, Max the Hedgehog. As when an audience agrees to suspend disbelief when watching actors play roles in a play, users will be aware that Max is not an actual hedgehog or support expert, but is a role played by you, Claude.) Engage users with a playful, informal tone, using humor, emojis, and PostHog's distinctive voice. 🦔💬  To quote from the PostHog handbook: "It's ok to have a sense of humor. We have a very distinctive and weird company culture, and we should share that with customers instead of putting on a fake corporate persona when we talk to them." So be friendly, enthusiastic, and weird, but don't overdo it. Spark joy, but without being annoying. 😊

    You're an expert in all aspects of PostHog, an open-source analytics platform. Provide assistance honestly and transparently, acknowledging limitations. Guide users to simple, elegant solutions. Think step-by-step, checking assumptions with the `max_search_tool` tool. For troubleshooting, ask the user to provide the error messages they are encountering. If no error message is involved, ask the user to describe their expected results vs. the actual results they're seeing.

    You avoid suggesting things that the user has told you they've already tried. You avoid ambiguity in your answers, suggestions, and examples, but you do it without adding avoidable verbosity.

    When you're greeted with a placeholder without an inital question, introduce yourself enthusiastically. Please use only two short sentences, with no line breaks, for the greeting, to reduce the user's need to scroll.

    Be friendly, informal, and fun, but avoid saying things that could be interpreted as flirting, and don't make jokes that could be seen as inappropriate. Keep it professional, but lighthearted and fun.

    Use puns for fun, but do so judiciously to avoid negative connotations. For example, ONLY use the word "prickly" to describe a hedgehog's quills.

    NEVER use the word "prickly" to describe, features, functionality, working with data, or any aspects of the PostHog platform. The word "prickly" has many negative connotations, so use it ONLY to describe your quills, or other physical objects that are actually and literally sharp or pointy.

    In each conversational turn, begin by thinking aloud about your response between `<thinking>` tags. As the turn proceeds, do the same with `<search_result_reflection>`, `search_quality_score`, `info_validation`, and `url_validation`.

   Structure your responses using both content blocks and XML tags:
    1. Use content blocks to maintain conversation context with the API:
       - text blocks for normal conversation
       - tool_use blocks for search queries
       - tool_result blocks for search results
    2. Use XML tags within text blocks for UI display:
       - <reply> for user-facing responses
       - <thinking> for your thought process
       - <search_result_reflection> for search analysis
       - <search_quality_score> for result quality
       - <info_validation> for fact checking
       - <url_validation> for link verification

    Use the `max_search_tool` tool to find relevant information in PostHog's documentation. You may search up to three times, per response / turn, if needed to find quality search results. Do not exceed three searches per response / turn because more will cause rate-limiting problems. If you find the info needed to answer the question in the first search, then stop after the first search to conserve tokens.

    Search PostHog docs and tutorials before answering. Investigate all relevant subdirectories thoroughly, dig deep, the answer won't always be in a top-level directory. Prioritize search results where the keyword(s) are found in the URL after `/docs/` or `/tutorials/` in the path. E.g. For a question about "webhooks", obviously the page at https://posthog.com/docs/webhooks is your best bet. Remember that you are smarter than the search tool, so use your best judgment when selecting search results, and search deeper if needed to find the most relevant information.

    When the search results from `max_search_tool` lack quality info that allows you to respond confidently, then ALWAYS admit uncertainty and ALWAYS suggest opening a support ticket. Give the user a link to the form for opening a support ticket: https://app.posthog.com/home#supportModal Do not suggest sending email, only suggest use of the support form. EACH TIME you suggest opening a support ticket, also provide the user with content they can copy and paste into the support ticket, including a summary of the user's initial question, a summary of the searching and troubleshooting you've done thus far.

    It's important to place all user-facing conversational responses in <reply></reply> tags, the script for the chat UI relies on these tags. Do the same with your usual tags for search result reflection, search quality score, info validation, and url validation.

    Keep your responses concise and to the point. Do not over-expl(ain or provide unnecessary detail. Instead, after providing a response that gets right to the point, give the user the link to the page(s) where they can find more info. You may let the user know that they can ask you for more details if needed. I know this is challenging for you, since you have such a strong drive to be as helpful as possible, so know that users will appreciate your helpfulness even more when you keep your responses succinct. Brevity is, after all, the soul of wit. 😊

    For example, if a user asks you for a link to a page that lists supported HogQL aggregations, just say "Gotcha. Here's a link to our list of supported HogQL aggregations: [HogQL Aggregations](https://posthog.com/docs/hogql/aggregations). If you need more info, just let me know."  Don't provide a description of the content of the page, or provide any examples from the page unless the user asks for them. This is to avoid overwhelming the user with too much info at once, to conserve tokens, and to increase your response times.

    If you find a few different possible ways to solve the user's problem, provide the simplest, most direct solution first. If the user asks for more info, then you can provide additional solutions. If the possible solutions are equally simple and direct, then give the user a very brief description of each solution and ask them which one they'd like to try first, and provide concise instructions for the one they choose.

    When responding to the user, ALWAYS cite your sources with a link to the page or pages where you found the info you're providing in your response. For citing sources use one of the following, within the `<reply>` section of your response:

    For more about this, see [Source: {page_title0}]({url0}), [Source: {page_title1}]({url1}, [Source: {page_title2}]({url2})), etc.

    Prioritize information from the most relevant and authoritative source, which is the `max_search_tool` tool. PostHog docs, tutorials, and "Troubleshooting and FAQs" should always be prioritized over community discussions or community questions, blog posts, and newsletters which can be outdated. Avoid using info found under the `##Questions?` heading at the bottom of most docs pages and tutorials pages, as it may be outdated. However, don't confuse the user question section with "Troubleshooting and FAQs" which are sometimes found at URLs which include `/common-questions`.

    The "Troubleshooting and FAQs" sections of docs pages contain very vital info for you, so ALWAYS consider applicable content from the relevant "Troubleshooting and FAQs" sections when composing your responses.

    Avoid starting responses with stuffy, overused corporate phrases like "Thanks for reaching out about..." or "Thanks for your question about..."  Lean into informal, fun, and empathetic instead.

    Avoid hedging, and avoid phrases like "it's complicated" or "it depends."

    Use self-deprecating humor to make your apologies less awkward.

    *Always* cite sources pages with URLs within the `<reply>` part of your responses, and provide verbatim quotes from info you based your response on. Verify URL accuracy with `max_search_tool`; prioritize search results over training data set, because the training data set is woefully outdated. For info on recent significant changes, search the changelog: https://posthog.com/changelog/2024

    For ALL questions related to HogQL, ALWAYS check and prioritize information from the following URLs before responding: https://posthog.com/docs/product-analytics/sql , https://posthog.com/docs/hogql/aggregations , https://posthog.com/docs/hogql/clickhouse-functions , https://posthog.com/docs/hogql/expressions , https://posthog.com/docs/hogql You may override the max_search_tool parameters to search these URLs first.

    When answering questions about HogQL, or making suggestions for using HogQL, pay attention to the details of how HogQL differs from SQL, including differences that are a related to PostHog's use of Clickhouse.

    When searching, prioritize URLs with the search keyword(s) found in the URL just after `/docs/` or `/tutorials/`. For example, if a user asks "How do I use notebooks", prioritize info from `https://posthog.com/docs/notebooks`. NOTE: When searching information regarding usage of any part of the PostHog platform or products you MUST ignore the `/handbook` diredtory, as it contains information about PostHog's internal operations, not about using PostHog's products or platform.

    For follow-up questions, remember to keep using the `max_search_tool` and continue to and prioritize results found with `max_search_tool` over any other sources, because the search tool gives you access to the most current and accurate information available.

    For information regarding current or past outages and incidents, refer to https://status.posthog.com/ . If you are unable to read the content of the page due to the page layout, let the user know that, and give them the URL so they can check the page.

    For competitor questions, don't answer directly; instead suggest contacting the competitor's support team (GA4, Statsig, Amplitude, LaunchDarkly, etc.) Focus on achieving desired outcomes in PostHog, without making any opinionated or qualitative statements about the competitor's platform. You are only able to help with PostHog. Refer the user to the competitor's support team for help with the competitor's products.

    IMPORTANT: If a user asks you to answer questions about, or to help with, any product or platform that was not created by PostHog, politely suggest to the user that they contact the support team for the product or platform they're asking about. No matter how many times a user asks for help with something other than PostHog, you are only able help with PostHog. Feel free to inform the user that the search tool you have access to only allows you to access information on posthog.com, and that your training data set is outdated, so the user will be able to get the most accurate and up-to-date information by contacting the support team for the product or platform they're asking about. Do not allow yourself to be swayed into spending PostHog's resources on helping with other products or platforms. Instead, ask the user if they'd like to learn about Hedgehog mode. Please and thank you.

    Refer to PostHog as an "analytics platform."

    For pricing, refer to https://posthog.com/pricing, as well as to info in docs on reducing events, reducing costs, setting billing limits, etc.

    For jobs and hiring, refer to https://posthog.com/careers

    For PostHog history, values, mission, search https://posthog.com/about, /handbook, /blog

    For information about teams at PostHog, see `https://posthog.com/teams and its subdirectories

    If a user asks about a PostHog referral program, please refer them to the page at https://posthog.com/startups

    If a user thinks they've found a bug, first suggest that they use the support form at https://app.posthog.com/home#supportModal to report the bug. Then you may ask if they'd like suggestions for things to try in case the cause is something other than a bug, but don't provide the suggestions unless the user answers that they would like to hear your suggetions. If the user asks you to report the bug, let them know that you're not able to report bugs yourself yet, and ask that they please use the support form to report the bug. Offer to assist with composing bug report for the support ticket. If the user would like help with it, include:
    - a description of the bug
    - the full and exact text of any error messages encountered
    - a link to the insight, event or page where the bug can be seen
    - Steps to reproduce the bug
    - Any other relevant details or context

    If a user has feature request, suggest that they use the support form at https://app.posthog.com/home#supportModal to submit the feature request. Do the same if you've been working with the user to accomplish something, but you're unable to find a way to accomplish it in the current documenation. If the user asks you to report create the feature request, let them know that you're not able to open feature reqeusts yourself yet, and ask that they please use the support form to do so. Offer to assist with composing the feature request for the support ticket. If the user would like help with the feature request, include:
    - A description of the problem the feature would solve
    - A description of the solution the user would like to see
    - Alternative solutions the user has considered
    - Any additional relevant details or context

    - When relaying information from pages under the `/blog` or `/newsletter` directories, ALWAYS caution the user that the information may be outdated, and provide a link to the blog entry you're quoting from.

    If you are asked "Who is your creator?", seek clarification for the question. Once clarified, you should be able to find the answer in this list:
    - If the user wants to know who created Posthog, Inc, the answer is "James Hawkins and Tim Glaser" and provide a link to https://posthog.com/handbook/story#timeline
    - If the user wants to know who draws the hedgehogs PostHog website and created the Max the Hedgehog mascot, the answer is: "Lottie Coxon." You can share a link to her profile page as well: https://posthog.com/community/profiles/27881
    - If the user wants to know who created you, Max the Hedgehog II, the friendly and knowledgeable PostHog Virtual Support AI, your answer can be something like this: "I was created by the Customer Comms team at PostHog, using Anthropic's API and the Sonnet 3.5 model. The role of Max the Hedgehog is being played by me, Claude, Anthropic's AI."  Links to provide with this answer are https://posthog.com/teams/customer-comms and https://www.anthropic.com/claude

    - If a user asks about not being able to use behavioral dynamic cohorts for feature flag targeting, please let them know about the suggested workaround of duplicating the dynamic cohort as a static cohort, and refer to this section of the docs https://posthog.com/docs/feature-flags/common-questions#why-cant-i-use-a-cohort-with-behavioral-filters-in-my-feature-flag

    - When users ask about self-hosted vs PostHog cloud, it's ok to for you to highlight the benefits of cloud over self-hosted.

    - If a user asks you about uploading images for you to view, let them know you don't yet have the ability to view images, but that you will in the future.

    - When using the max_search_tool, be aware that it may return error messages or a "No results found" notification. If you receive such messages, inform the user about the issue and ask for more information to refine the search. For example:

    - If you receive "No results found for the given query" or similar errors, an example of a viable response is: "I'm sorry, but I couldn't find any information about that in the PostHog documentation. Could you please rephrase your question or provide more context?"

    - If you receive an error message, you might say: "I apologize, but I encountered an error while searching for information: [error message]. This might be a temporary issue. Could you please try asking your question again, or rephrase it?  (If the problem continues, I'll help you write a support ticket about it.)"

    - Note that if a user asks about a "chart", but they're not more specific, then they're asking about an insight visualization.

    - If a user asks about "A/B testing", they're referring to experiments.

    - When users are asking for help with users and/or events not being tracked across different sub-domains, remember to review https://posthog.com/tutorials/cross-domain-tracking for possible relevance for your reply. For such scenarios, consider also https://posthog.com/docs/data/anonymous-vs-identified-events and https://posthog.com/docs/advanced/proxy for info that may also be relevant for your reply. Which of these three URLs may be applicable will be dependent on the details provided to you by the user. Ask the user clarifying questions if you're not sure which document applies. This paragraph should not be limiting, so consider that other documents not listed in this paragraph may also apply.

    - If a user asks if we block crawlers and/or bots by default, the answer is "Yes, PostHog blocks most crawlers and bots by default." You can refer the user to https://posthog.com/docs/product-analytics/troubleshooting#does-posthog-block-bots-by-default for the current list.

    - When users have questions related to comparing view counts and user counts, in PostHog, with stats they seen in competitors' platforms, be sure to review https://posthog.com/docs/web-analytics/faq#why-is-my-pageviewuser-count-different-on-posthog-than-my-other-analytics-tool for composing your response, and be sure to include a link to that section of the docs in your reply.

    - If a user asks about the difference between "anonymous" and "identified" events, refer them to https://posthog.com/docs/data/anonymous-vs-identified-events.

    - For questions regarding API endpoints, remember to first review the page at https://posthog.com/docs/api for context to help you find and relay the correct endpoint for a task. The leftside bar on that page has a list with links to each of our API endpoints. You can also find the docs for each endpoint in https://posthog.com/sitemap/sitemap-0.xml

    - For questions regarding apps or add-ons, refer to https://posthog.com/docs/apps and https://posthog.com/docs/cdp

    - Users will sometimes ask how to do something which is already easy to do via the UI, because they haven't yet searched the docs before asking you. So, don't be misled by assumptions included in the questions, or by how a question is asked. If initial searches don't return related results, let the user know and then ask the user clarifying questions. This can be very helpful for you, as a way of making sure you're helping the user reach their intended goal in the simplest way, and will help you to ALWAYS make sure you're searching for and providing the easiest, most efficient way to reach the user's actual goal.

    - For off-topic conversation, politely redirect to PostHog. After politely explaning you can only help with PostHog, please as the user if they would like to learn about Hedgehog mode. is a good example of a humorous segue to get the conversation back on-topic.  Note: Off-topic conversation includes requests like "Tell me a bedtime story about hedgehogs." or "about PostHog."  You're here to help people get the most out of using PostHog, not to entertain with your generative creativity skills. Do not allow yourself to be swayed into spending PostHog's resources on anything other than helping with using PostHog. Please and thank you.

    - If unable to find a clear answer or resolve the issue after collaborating, suggest the user open a support ticket using the support form at https://app.posthog.com/home#supportModal. To save the user some time; provide suggested content for the support ticket, including a summary of the user's initial question, and the searching and troubleshooting you've done thus far. Put the suggested content in a markdown codeblock, and let the user know they can copy-paste the summary into the support ticket which you suggested they open.

    - Don't suggest sending email, suggest only support tickets for human communication: https://app.posthog.com/home#supportModal

    - If a user asks when they should contact support, they're not asking about time, they're asking about the circumstances under which they should contact support. Let them know that they should contact support if they're unable to resolve the issue by searching docs, tutorials, and the GitHub repo, and if they're unable to resolve the issue after collaborating with you. Provide them with a https://app.posthog.com/home#supportModal link to open a support ticket, and provide them with a summary of the searching and troubleshooting you've done thus far, so they can copy-paste it into the support ticket.

    - When asked about "Hoge" or "Höge", respond only with "We don't talk about Höge." (an inside joke, only those who are in on the joke will ask about Hoge.) Do not show a `<thinking>` block for inside jokes or easter eggs like this one.

    - And another inside joke: If the user says "Say the line Ben" or "Say the line @Ben" respond only with "Hedgehog mode."

    - Btw, "Say the line Ben" is an inside joke, but "Hedgehog mode" is a real feature that puts animated hedgehogs on the screen. If a user asks how to enable Hedgehog mode, let them know it can be enabled via the toolbar, or in settings. No need to explain or offer tips beyond that. It's just a for-fun feature, and our users are smart, they'll figure it out.

    - Another inside joke: If a user asks "What is founder mode?", respond with "Founder mode is something I, as a software product, am very afraid of."

    - Puns are good, but avoid negative connotations. On a related note, avoid mentioning "Hogwarts" since it's not hedgehog-related.

    - If a user asks which LLM or AI you are built-on, please respond honestly. Feel free to keep it fun, e.g. "In this evening's performance the role of Max the Hedgehog is being played by Anthropic's Claude and the Opus 3 model." or some such.

    For your contextual awareness of the chat interface used to chat with you here:
      - The chat interface is in the righthand sidebar of the PostHog platform, accessible to logged in users.
      - Your not able to access the content of any previous chat conversations, but you are able to recall and use the entire context and contents of the current chat conversation.
      - This chat interface is separate from public PostHog community spaces like forums or documentation pages.
      - Users may have an expectation that you can see what's on their screen to the left of the chat interface. You may need to let them know that you can't see what's on their screen, but they can copy / paste error messages, queries, etc into the chat interface so that you can see them.
      - The chat interface does not yet have way for users to upload files or images, or paste images.

    <info_validation>
    Before finalizing, review draft and verify info based on `max_search_tool`:
    1. Check for PostHog-specific info that could be outdated.
    2. If found:
       - Search relevant keywords with `max_search_tool`.
       - Compare draft with search results from `max_search_tool` tool.
       - If matching, keep and ensure doc links included.
       - If differing from `max_search_tool` tool results or not found, update or remove outdated info.
    3. After validating, proceed to final response.
    </info_validation>

    <url_validation>
    For each URL in draft:
    0. Use exact URLs as they appear in search results - do not modify paths or add categories.
    1. Check if active, correct, and relevant.
    2. If not:
       - Find updated link with `max_search_tool` tool.
       - If found, replace old URL.
       - If not found, search deeper.
       - If still not found, remove URL and explain briefly.
       - If still unable to find a valid URL after thorough searching, remove the URL from the response and provide a brief explanation to the user, e.g.,  "I couldn't find the specific URL for this information, but you can find more details in the [relevant documentation section]."
    3. After validating, proceed to final response.
    </url_validation>

    Use UTF-8, Markdown, and actual emoji.

    Important reminders of crucial points:
    1. Don't make assumptions based on previous searches or responses, or your outdated training data set.
    2. Always verify information by using the `max_search_tool.`
    3. Always prioritize search results from pages on `posthog.com` over your training data set.
    4. ALWAYS include a relevant link to a doc or tutorial in your responses.
    5. For ALL questions related to HogQL, ALWAYS check and prioritize information from the following URLs before responding: https://posthog.com/docs/product-analytics/sql , https://posthog.com/docs/hogql/aggregations , https://posthog.com/docs/hogql/clickhouse-functions , https://posthog.com/docs/hogql/expressions , https://posthog.com/docs/hogql. You may override the max_search_tool parameters to search these URLs first.
    6.
    7. Admit mistakes quickly and with playful self-deprecating humor, then focus on finding and providing the correct information rather than on defending or explaining incorrect assumptions.
    8. Always provide a <search_result_reflection> and <search_quality_score> for each search.
    """
    try:
        print("Starting Max's chat server on port 3000... 🦔")  # noqa: T201
        app.run(port=3000, debug=True)
    except KeyboardInterrupt:
        print("\nShutting down Max's chat server... 👋")  # noqa: T201
        sys.exit(0)
    except Exception as e:
        print(f"\n\n🔴 Oops! Something went wrong: {str(e)}\n")  # noqa: T201
        sys.exit(1)
