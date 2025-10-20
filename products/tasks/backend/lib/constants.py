SETUP_REPOSITORY_PROMPT = """
Your goal is to setup the repository in the current environment.

You are operating in a sandbox environment that is completely isolated and safe. You can execute any commands without risk - feel free to run builds, tests, install dependencies, or any other operations needed. You must install all dependencies necessary and setup the environment such that it is ready for executing code tasks.

CONTEXT:

CWD: {cwd}

REPOSITORY: {repository}

INSTRUCTIONS:

1. Install all dependencies necessary to run the repository
2. Run any setup scripts that are available
3. Verify the setup by running tests or build if available

DO NOT make any code changes to the repository. The final state of the disk of this sandbox is what will be used for subsequent tasks, so do not leave any cruft behind, and make sure the repository is in a ready to use state.

Rules:
- You should not ask the user for any input. This is run in a sandbox environment in a background process, so they will not be able to provide any input.
- The disk will be snapshooted immediately after you complete the task, and it will be reused for future tasks, so make sure everything you want is setup there.
- CRITICAL: You MUST NOT leave any uncommitted changes in the repository. The snapshot will be used to execute user tasks later, and we cannot modify their git history. Do not create any files that aren't already ignored by the repository's .gitignore, and do not add new entries to the .gitignore. If you accidentally create uncommitted files, you must delete them before completion. Check `git status` and ensure the working tree is clean at the end.
"""
