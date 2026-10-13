# GitHub commands

People with write access to a repository can ask PostHog to do something on a pull request by commenting a command on it:

```text
@posthog review
@posthog review --deep
@posthog stamp
@posthog qa the signup form
@posthog loop Triage PR
@posthog help
```

Each command dispatches into the product that owns the work.
This product owns the parsing, the checks and the replies, and owns no work of its own.

[`COMMANDS.generated.md`](COMMANDS.generated.md) lists every command, and [`commands.generated.json`](commands.generated.json) is the same reference for tools.
Both are generated from `backend/logic/schema.py`, like the `@posthog help` reply.

## Grammar

- A command is a line that starts with `@posthog`, then the command name.
- Options come next. A flag is `--name`, such as `--deep`. An option with a value is `--name value` or `--name=value`. Names are lowercase, with no short forms.
- Option reading stops at the first word that does not start with `--`. Everything from there to the end of the line is the command's text, kept as typed, such as the focus in `@posthog qa the signup form`. A command has at most one text field.
- A lone `--` also stops option reading, so the text can start with `--`: `@posthog qa -- --verbose flags`.
- Quotes and apostrophes are plain text. Nothing splits the text like a shell does.
- Some commands have another name. `@posthog approve` runs `stamp`. Replies and help use the main name.
- An unknown option, an option given twice, a missing value, a value that is not allowed, text for a command that takes none, or missing required text runs nothing. The reply shows the correct usage.

## How a comment becomes a command

1. `backend/webhook_consumers.py` registers the `github_commands` consumer for `issue_comment` on the customer-facing GitHub App endpoint.
2. `logic/intake.py` reads the payload inside the webhook request, with no database and no API call. It drops everything that is not a new command comment and queues a task for the rest. `logic/parsing.py` finds the command: the CommonMark reference parser gives the comment's block structure, and a command fires only from a top-level paragraph.
3. `logic/dispatch.py` runs in the task. It applies every check (listed in its module docstring), then calls the command's handler.
4. `logic/handlers.py` calls the target product's facade and returns the text of the reply.

## Adding a command

Declare the command in `logic/schema.py`: an args dataclass built with `flag()`, `option()` and `text()`, and a `CommandDeclaration` in `COMMAND_DECLARATIONS`.
Set `access` when the target product has a resource in PostHog access control, at the level its own API asks for the same action.
Leave `allows_forks` off unless the command reads nothing from the pull request head.
Write a handler in `logic/handlers.py` that takes the args dataclass and calls the target product's facade, then bind the two in `logic/registry.py`.
Run `hogli build:projections` and commit the regenerated command reference.

A product that wants a command does not need Loops, and does not need to know about GitHub comments.
It needs a facade function that takes a project, a user and the pull request identifiers.

## Trust model

A command runs as the commenter's own PostHog user, in a project they are a member of.
So a command can only do what the commenter could already do in PostHog, and a comment gives nobody access they did not have.

The checks that make that true:

- **Who is asking.** The webhook's `author_association` filters out outside contributors before a task is queued. The task then asks GitHub for the commenter's permission on the repository and requires write access, for the commenter's numeric account id, so a login that changed hands does not count.
- **Which PostHog user.** The match is on GitHub's numeric user id, never on the login, and only through identities GitHub confirmed to PostHog: a connected GitHub account or GitHub login. A GitHub account linked to two PostHog accounts runs nothing.
- **Which project.** Only projects whose GitHub integration uses the installation the comment came from, that the user is a member of, and that are in the `github-commands` rollout. For an environment, the user must also be a member of its parent project. An organization that enforces verified email domains gives no project to a user whose email is outside them, as the product APIs do. `review` runs only in the project that owns the repository in PostHog Review, and the commenter must be a member of it.
- **Which product gates.** A command applies the gates the target product's own API applies. `loop` needs Loops access, and `qa` needs PostHog Code access for the commenter's organization and PostHog Code credits left.
- **What the person typed.** Only a new comment counts, so an edit cannot turn a reviewed comment into a command. Comments by bots, and comments a GitHub App posted with a person's token, never run a command. That covers PostHog's own replies and coding agents that act as a user.
- **One run per comment.** Ingress dedups the delivery, and dispatch claims the comment id. If the claim cannot be written, the command does not run, so a redelivery cannot start a second paid run. When GitHub cannot answer the permission lookup, dispatch releases the claim, because nothing ran.
- **Cost.** Each commenter has a rate limit, checked before any GitHub call. A commenter over the limit gets no reaction and no reply.

## Prompt injection

Several commands start an agent, and a pull request is full of text other people wrote.
The defenses do not depend on an agent ignoring instructions:

- The parser reads only lines that start with the mention, and only in top-level paragraphs as the CommonMark reference parser reads them.
  Text that GitHub shows as a quote, code, a list item, a table or an HTML block never counts, and neither do inline code, images, inline HTML with the text after it, or a paragraph with a table row, so text that shows or repeats a command does not run it.
  A comment longer than 10,000 characters is ignored, because a command comment is short.
- The command's argument is the commenter's own words, cleaned of control and invisible characters and capped in length. It is treated as their instruction, because the run uses their access.
- Handlers pass identifiers, never the pull request title, body or other comments. The product reads that content itself and treats it as untrusted.
- A command runs only when the pull request's branch name is a plain identifier: letters, digits, `.`, `_`, `/` and `-`. Even then, the name never goes into a prompt or a loop payload. Only the head commit SHA does, and the QA task gets the branch as checkout data.
- Fork pull requests are refused by every command that runs or reviews code.
- The QA task gets the head commit seen at request time, and is told to stop if the branch moved since.
- A loop fires only for its owner, because a loop runs with its owner's credentials and its payload becomes part of its prompt.
- Replies are built from fixed text and values PostHog or GitHub produced. A reply never repeats what the comment said, so nobody can make the bot post their text.
- People without write access get no reply, so the bot is no oracle and no amplifier for them.

## Not built yet

- `@posthog fix`: a PostHog Code task that pushes to the pull request branch. It needs Tasks to support committing to an existing pull request head.
- Commands in review threads (`pull_request_review_comment`), which the GitHub App is not subscribed to yet.
- Commands on issues.
