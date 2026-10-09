# GitHub commands

People with write access to a repository can ask PostHog to do something on a pull request by commenting a command on it:

```text
@posthog review
@posthog stamp
@posthog qa the signup form
@posthog loop Triage PR
@posthog help
```

Each command dispatches into the product that owns the work.
This product owns the parsing, the checks and the replies, and owns no work of its own.

| Command                  | Dispatches to                                  | What happens                                                                                                                       |
| ------------------------ | ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `@posthog review [full]` | PostHog Review (`review_hog` facade `reviews`) | Starts a Flash review, or the full review with `full`, with the commenter as the acting user. It never pushes fixes to the branch. |
| `@posthog stamp`         | Stamphog (`stamphog` facade `review_requests`) | Queues a Stamphog review. Stamphog alone decides whether to approve.                                                               |
| `@posthog qa [focus]`    | PostHog Code (`tasks` facade `api`)            | Starts a task that runs the `qa-frontend` skill on the pull request head.                                                          |
| `@posthog loop <name>`   | Loops (`tasks` facade `loops`)                 | Fires one of the commenter's own loops, with the pull request as its input.                                                        |
| `@posthog help`          | none                                           | Lists the commands.                                                                                                                |

## How a comment becomes a command

1. `backend/webhook_consumers.py` registers the `github_commands` consumer for `issue_comment` on the customer-facing GitHub App endpoint.
2. `logic/intake.py` reads the payload inside the webhook request, with no database and no API call. It drops everything that is not a new command comment and queues a task for the rest.
3. `logic/dispatch.py` runs in the task. It applies every check (listed in its module docstring), then calls the command's handler.
4. `logic/handlers.py` calls the target product's facade and returns the text of the reply.

## Adding a command

Write a handler in `logic/handlers.py` that calls the target product's facade.
Declare it in `logic/registry.py`.
Set `access` when the target product has a resource in PostHog access control, at the level its own API asks for the same action.
Leave `allows_forks` off unless the command reads nothing from the pull request head.

A product that wants a command does not need Loops, and does not need to know about GitHub comments.
It needs a facade function that takes a project, a user and the pull request identifiers.

## Trust model

A command runs as the commenter's own PostHog user, in a project they are a member of.
So a command can only do what the commenter could already do in PostHog, and a comment gives nobody access they did not have.

The checks that make that true:

- **Who is asking.** The webhook's `author_association` filters out outside contributors before a task is queued. The task then asks GitHub for the commenter's permission on the repository and requires write access, for the commenter's numeric account id, so a login that changed hands does not count.
- **Which PostHog user.** The match is on GitHub's numeric user id, never on the login, and only through identities GitHub confirmed to PostHog: a connected GitHub account or GitHub login. A GitHub account linked to two PostHog accounts runs nothing.
- **Which project.** Only projects whose GitHub integration uses the installation the comment came from, that the user is a member of, and that are in the `github-commands` rollout.
- **Which product gates.** A command applies the gates the target product's own API applies. `loop` needs Loops access, and `qa` needs PostHog Code access for the commenter's organization.
- **What the person typed.** Only a new comment counts, so an edit cannot turn a reviewed comment into a command. Comments by bots, and comments a GitHub App posted with a person's token, never run a command. That covers PostHog's own replies and coding agents that act as a user.
- **One run per comment.** Ingress dedups the delivery, and dispatch claims the comment id. If the claim cannot be written, the command does not run, so a redelivery cannot start a second paid run.
- **Cost.** Each commenter has a rate limit, checked before any GitHub call. A commenter over the limit gets no reaction and no reply.

## Prompt injection

Several commands start an agent, and a pull request is full of text other people wrote.
The defenses do not depend on an agent ignoring instructions:

- The parser reads only lines that start with the mention. Quoted replies, code blocks, inline code and HTML comments never count, so text that shows or repeats a command does not run it.
- The command's argument is the commenter's own words, cleaned of control and invisible characters and capped in length. It is treated as their instruction, because the run uses their access.
- Handlers pass identifiers, never the pull request title, body or other comments. The product reads that content itself and treats it as untrusted.
- Fork pull requests are refused by every command that runs or reviews code.
- The QA task gets the head commit seen at request time, and is told to stop if the branch moved since.
- A loop fires only for its owner, because a loop runs with its owner's credentials and its payload becomes part of its prompt.
- Replies are built from fixed text and values PostHog or GitHub produced. A reply never repeats what the comment said, so nobody can make the bot post their text.
- People without write access get no reply, so the bot is no oracle and no amplifier for them.

## Not built yet

- `@posthog fix`: a PostHog Code task that pushes to the pull request branch. It needs Tasks to support committing to an existing pull request head.
- Commands in review threads (`pull_request_review_comment`), which the GitHub App is not subscribed to yet.
- Commands on issues.
