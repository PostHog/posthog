SETUP_REPOSITORY_PROMPT = """
Your goal is to setup the repository in the current environment.

You are operating in a sandbox environment. You must install all dependencies necessary and setup the environment such that it is ready for executing code tasks.

CONTEXT:

CWD: {cwd}

REPOSITORY: {repository}

INSTRUCTIONS:

1. Install all dependencies necessary to run the repository
2. Run any setup scripts that are available
3. Verify the setup by running tests or build if available

DO NOT make any code changes to the repository. The final state of the disk of this sandbox is what will be used for subsequent tasks, so do not leave any cruft behind, and make sure the repository is in a ready to use state.
"""
