import asyncio
import json
import logging
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from claude_code_sdk import (
    ClaudeCodeOptions,
    Message,
    ResultMessage,
    query,
)
from claude_code_sdk.types import McpStdioServerConfig
from dotenv import load_dotenv
from pydantic import BaseModel

from reviewer.constants import (
    MAX_CONCURRENT_CODE_RUNS_CLAUDE,
    MAX_CONCURRENT_CODE_RUNS_CODEX,
)
from reviewer.tools.github_meta import PRFile
from reviewer.utils.json_utils import extract_json_from_text

# Load environment variables
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)

# Pricing of GPT-5 in USD per million tokens
GPT_5_PRICING = {
    "input": 1.25,
    "output": 10.00,
    "cached_input": 0.125,
}

# Define max concurrence based on the tool, as TPM limits differ
_max_concurrent = MAX_CONCURRENT_CODE_RUNS_CODEX if os.getenv("USE_CODEX") else MAX_CONCURRENT_CODE_RUNS_CLAUDE
_run_code_semaphore = asyncio.Semaphore(_max_concurrent)


class CodeExecutor:
    def __init__(
        self,
        prompt: str,
        system_prompt: str,
        project_dir: str,
        output_path: str,
        model_to_validate: type[BaseModel],
    ):
        """Initialize the code executor."""
        self.prompt = prompt
        self.system_prompt = system_prompt
        self.project_dir = project_dir
        self.output_path = output_path
        self.model_to_validate = model_to_validate

    async def _run_claude_code(self) -> bool:
        """
        Run Claude Code SDK with the given prompt and save output to the specified path.
        Returns True if successful, False otherwise.
        """
        logger.info(f"Using working directory: {self.project_dir}")
        # Prepare messages for the SDK
        messages: list[Message] = []
        # Prepare stream output path
        stream_output_path = str(self.output_path).replace(".json", "_stream.json")

        # Get Serena MCP path from environment
        serena_mcp_path = os.getenv("SERENA_MCP_PATH")

        # Configure MCP servers
        mcp_servers = {}
        if serena_mcp_path:
            logger.info(f"Configuring Serena MCP from: {serena_mcp_path}")
            mcp_servers["serena"] = McpStdioServerConfig(
                type="stdio",
                command="uv",
                args=[
                    "run",
                    "--directory",
                    serena_mcp_path,
                    "serena",
                    "start-mcp-server",
                    "--enable-web-dashboard",
                    "False",
                    "--context",
                    "agent",
                    "--mode",
                    "no-onboarding",
                    "--mode",
                    "planning",
                    "--mode",
                    "one-shot",
                    "--project",
                    self.project_dir,
                ],
            )
            logger.info(f"Serena MCP configured: {mcp_servers['serena']}")

        try:
            logger.debug("Running Claude Code SDK...")
            # Query Claude using the SDK
            code_query = query(
                prompt=self.prompt,
                # TODO Provide options as parameter (to define different options for different tasks)
                options=ClaudeCodeOptions(
                    cwd=self.project_dir,
                    max_turns=50,  # Limit turns since we just need JSON output
                    # max_thinking_tokens=32798,
                    allowed_tools=[
                        "Task",
                        "Bash",
                        "Glob",
                        "Grep",
                        "LS",
                        "Read",
                        "TodoWrite",
                        # Don't allow web access (for now)
                        # Serena MCP (read/search operations)
                        "mcp__serena__read_file",
                        "mcp__serena__list_dir",
                        "mcp__serena__find_file",
                        "mcp__serena__search_for_pattern",
                        "mcp__serena__get_symbols_overview",
                        "mcp__serena__find_symbol",
                        "mcp__serena__find_referencing_symbols",
                        # TODO: Decide if it's worth it
                        "mcp__serena__think_about_collected_information",
                    ],
                    mcp_servers=mcp_servers,
                    system_prompt=self.system_prompt,
                    permission_mode="default",
                ),
            )
            async for message in code_query:
                messages.append(message)
                # Write to stream file for monitoring
                with Path(stream_output_path).open("w") as sf:
                    json.dump([asdict(x) for x in messages], sf, indent=2)
            # Extract JSON from the response
            final_message = None
            for message in messages:
                # Consume only the result message
                if not isinstance(message, ResultMessage):
                    continue
                else:
                    final_message = message
            if not final_message:
                raise ValueError(f"No valid JSON found in Claude's response: {messages}")
        except Exception as e:
            logger.error(f"Error getting final message from Claude Code SDK: {e}")
            return False
        try:
            result_text = final_message.result
            # Extract and parse JSON from the text
            json_data = extract_json_from_text(text=result_text, label="Claude output")
            validated_data = self.model_to_validate.model_validate(json_data)
            # Save to output file
            with Path(self.output_path).open("w") as f:
                f.write(json.dumps(validated_data.model_dump(mode="json"), indent=2))
            logger.info(f"Successfully saved validated data to: {self.output_path}")
            return True
        except Exception as e:
            error_output_path = str(self.output_path).replace(".json", "_error.txt")
            if not final_message.result:
                logger.error(f"Error processing output for Claude Code SDK, empty result: {e}")
                return False
            with Path(error_output_path).open("w") as f:
                f.write(final_message.result)
            logger.error(f"Error processing output for Claude Code SDK: {e}")
            return False

    async def _run_openai_codex(self) -> bool:
        """
        Run OpenAI Codex CLI with the given prompt and save output to the specified path.
        Returns True if successful, False otherwise.
        """

        logger.info(f"Using Codex with working directory: {self.project_dir}")

        # Prepare stream output path
        stream_output_path = str(self.output_path).replace(".json", "_stream.jsonl")
        result_text = None

        try:
            # Create a temporary file to store the prompt
            with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as prompt_file:
                # Combine system prompt and user prompt
                full_prompt = f"{self.system_prompt}\n\n{self.prompt}"
                prompt_file.write(full_prompt)
                prompt_file_path = prompt_file.name

            # Execute via shell to handle the $(cat ...) substitution
            shell_cmd = f'codex exec -s read-only --output-last-message {self.output_path} --skip-git-repo-check --json "$(cat {prompt_file_path})"'

            logger.debug(f"Running Codex CLI command: {shell_cmd}")

            # Use asyncio subprocess for async execution
            process = await asyncio.create_subprocess_shell(
                shell_cmd,
                cwd=self.project_dir,
                limit=2**16 * 64,  # 64KB * 64 = 4096KB
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Stream output to file and collect it
            stdout_lines = []

            # Open stream file for writing
            with Path(stream_output_path).open("w") as stream_file:
                # Read stdout in real-time asynchronously
                if process.stdout:
                    while True:
                        line = await process.stdout.readline()
                        if not line:
                            break
                        line_text = line.decode("utf-8")
                        stdout_lines.append(line_text)
                        # Write to stream file immediately
                        stream_file.write(line_text)
                        stream_file.flush()  # Ensure it's written immediately

                        # Optionally log it for debugging
                        logger.debug(f"Codex output: {line_text.rstrip()}")

            # Wait for process to complete and get return code
            return_code = await process.wait()

            # Read any remaining stderr
            stderr_data = b""
            if process.stderr:
                stderr_data = await process.stderr.read()
            stderr_text = stderr_data.decode("utf-8") if stderr_data else ""

            # Clean up the temporary prompt file
            Path(prompt_file_path).unlink(missing_ok=True)

            if return_code != 0:
                logger.error(f"Codex command failed with return code {return_code}")
                logger.error(f"stdout: {''.join(stdout_lines)}")
                logger.error(f"stderr: {stderr_text}")
                return False

            # Read and validate the output file
            output_file = Path(self.output_path)
            if not output_file.exists():
                logger.error(f"Codex output file not found: {self.output_path}")
                return False

            # Check if file is empty
            if output_file.stat().st_size == 0:
                logger.warning(f"Codex output file is empty, removing: {self.output_path}")
                output_file.unlink(missing_ok=True)
                return False

            with output_file.open() as f:
                result_text = f.read()
            if not result_text:
                logger.error(f"Codex output file is empty: {self.output_path}")
                return False

        except Exception as e:
            logger.error(f"Error getting result from Codex CLI: {e}")
            return False

        # Extract JSON, validate, and save
        try:
            # Extract and parse JSON from the text
            json_data = extract_json_from_text(text=result_text, label="Codex Output")
            validated_data = self.model_to_validate.model_validate(json_data)
            # Overwrite the output file with validated data
            with Path(self.output_path).open("w") as f:
                f.write(json.dumps(validated_data.model_dump(mode="json"), indent=2))
            logger.info(f"Successfully saved validated Codex data to: {self.output_path}")
            return True
        except Exception as e:
            # Save raw output to error file if validation fails
            error_output_path = str(self.output_path).replace(".json", "_error.txt")
            with Path(error_output_path).open("w") as f:
                f.write(result_text)
            logger.error(f"Error processing output for Codex: {e}")
            return False

    async def run_code(
        self,
    ) -> bool:
        """
        Run either Claude Code or OpenAI Codex based on USE_CODEX environment variable.
        Limits concurrent executions using a semaphore to avoid hitting API rate limits.
        Returns True if successful, False otherwise.
        """
        async with _run_code_semaphore:  # Acquire semaphore, wait if limit reached
            logger.info(f"Acquired semaphore for run_code with limit: {_max_concurrent}")
            use_codex = os.getenv("USE_CODEX")
            if use_codex:
                logger.info("USE_CODEX is set, using OpenAI Codex")
                return await self._run_openai_codex()
            else:
                logger.info("USE_CODEX not set, using Claude Code")
                return await self._run_claude_code()


def prepare_code_context(chunk_filenames: list[str], pr_files: list[PRFile]) -> str:
    """Prepare context with specific line ranges for changed code."""
    claude_code_context_lines = []
    for filename in chunk_filenames:
        # Find the corresponding PRFile to get changes
        pr_file = next((f for f in pr_files if f.filename == filename), None)
        if pr_file and pr_file.changes:
            # Collect line ranges for additions and deletions only
            line_ranges = []
            for change in pr_file.changes:
                if change.type not in ["addition", "deletion"]:
                    continue
                # Use new line numbers for additions, old for deletions
                if change.type == "addition" and change.new_start_line and change.new_end_line:
                    line_ranges.append((change.new_start_line, change.new_end_line))
                elif change.type == "deletion" and change.old_start_line and change.old_end_line:
                    line_ranges.append((change.old_start_line, change.old_end_line))

            # Merge overlapping or adjacent ranges
            if line_ranges:
                line_ranges.sort()
                merged_ranges: list[tuple[int, int]] = []
                for start, end in line_ranges:
                    if merged_ranges and start <= merged_ranges[-1][1] + 1:
                        # Merge with previous range
                        merged_ranges[-1] = (
                            merged_ranges[-1][0],
                            max(merged_ranges[-1][1], end),
                        )
                    else:
                        merged_ranges.append((start, end))
                # Generate context lines with specific ranges
                for start, end in merged_ranges:
                    if start == end:
                        claude_code_context_lines.append(f"@{filename}#L{start}")
                    else:
                        claude_code_context_lines.append(f"@{filename}#L{start}-{end}")
            else:
                # No changes, include whole file
                claude_code_context_lines.append(f"@{filename}")
        else:
            # No PRFile found or no changes, include whole file
            claude_code_context_lines.append(f"@{filename}")
    return "\n".join(claude_code_context_lines)
