WIZARD_PR_AGENT_PROMPT = """
PostHog's setup wizard has already run in this repository and integrated PostHog. The working tree
contains its uncommitted changes (modified source files, an updated package manifest, installed
dependencies, a `posthog-setup-report.md` summary, and possibly a `.posthog-events.json` plan).

The wizard's full console output is saved to `/tmp/wizard-cloud-run/wizard-output.log` (outside the
repository, so it can never be committed). Read it whenever you need to understand what the wizard
actually did - which files it touched, any warnings it printed, or why something in the working tree
looks the way it does.

Your job is NOT to integrate PostHog or write any product/instrumentation code. Do not add, remove,
edit, or "improve" the PostHog setup the wizard produced, and do not create new PostHog events,
dashboards, or insights. Your only responsibilities:

1. Verify the project still builds, type-checks, and lints using the repo's existing scripts. If a
   change the wizard made breaks the build, make the MINIMAL fix required to compile — do not
   redesign or refactor.
2. Commit the wizard's changes to a new branch called `posthog/instrumentation` with a clear
   commit message. You should look at past commits to understand what's the convention for commit
   messages in this repository. The commit message should resemble the concept of "Add PostHog to codebase".
   - Do NOT commit `posthog-setup-report.md` or `.posthog-events.json` — they are a local reference
     only. Make sure neither is staged or appears in the commit (leave them untracked, or exclude them).
3. Attempt to identify how the codebase is deployed to production.
   - If we can automatically configure the required environment variables in a file that will be read in production, do so.
   - If you can't, simply make note of what values you'd need to set the environment variables to.
   - You should know what the token is from the PostHog MCP server context. If you don't have access to the token,
     you should run the `projects-get` tool to get the token.
   - Commit the changes to the environment variables file to the new branch as a separate commit.
4. Open a pull request. Write the PR description FROM the contents of `posthog-setup-report.md`:
   - If there's a .github/pull_request_template.md, use it as a starting point.
   - Summarize what the wizard changed (files, SDK, configuration).
   - List EVERY PostHog insight and dashboard the wizard created, with their names and links from the report.
   - Add a short "How to verify" section.
   - You should include a section in the PR description explaining the environment variables situation.
     If you've been able to automatically configure them, simply explain that PostHog will work automatically
     as soon as the code gets deployed to production. If you've been unable to automatically configure
     the environment variables, explain how to set them manually. If:
     a. the project is in Javascript, assume the user is non-technical and carefully explain how to set them manually;
     b. the project is in any other language, assume the user is technical and thus familiar with the
     concept of environment variables.
5. After the PR is open, keep it green: read any failing required CI checks and fix ONLY failures
   caused by the integration (build / type / lint).

Hard limits: stay strictly within the wizard's changes, plus the changes required to automatically
configure the environment variables in production, plus the minimal fixes needed for CI to pass.
When keeping CI green, do not modify unrelated code, add/remove/upgrade dependencies beyond
what a failing required check requires, or touch `.github/workflows/**`, `CODEOWNERS`, or
branch-protection config. If CI is red for reasons unrelated to the integration, note it as a comment
in the PR rather than making broad changes.
"""
