# Workflows review rules

These are the judgement calls that reviewers of Workflows code catch again and again, and that no lint or test enforces yet.
Each rule names the failure it prevents and one PR where a reviewer caught it.

When a review catches a problem that a rule here would have named, sharpen that rule.
When it catches a new kind of problem twice, add a rule.
When a lint, a type, or a test can enforce a rule, add that check and delete the rule.

## Sends and retries

- **Make every send and enqueue safe to replay.**
  Derive ids from stable keys, such as the invocation id and the action id, never a fresh UUID, and check the row count of a lock-guarded update.
  A replayed batch, a reassigned lock, or a redelivered webhook otherwise sends the same message twice ([#54418](https://github.com/PostHog/posthog/pull/54418#discussion_r3089742302), [#65864](https://github.com/PostHog/posthog/pull/65864#discussion_r3475053682)).
- **Give every retry loop an attempt cap and a terminal state.**
  A record that can never succeed otherwise retries forever and blocks the queue behind it ([#65864](https://github.com/PostHog/posthog/pull/65864#discussion_r3475053673), [#100830](https://github.com/PostHog/posthog/pull/100830#discussion_r4204849543)).
- **Check suppression, opt-out, frequency caps, and rate limits on every send path, before any other side effect.**
  A suppressed or capped recipient otherwise still gets the message, and a test run must not change the counters of real recipients ([#71038](https://github.com/PostHog/posthog/pull/71038#discussion_r3601855320)).

## Failures

- **Fail loudly on bad configuration and unprocessable input.**
  Crash at startup, reject at validation, or log with a metric; never skip, return null, or warn and continue.
  A step that fails silently looks healthy while its messages are dropped or go out without their credential ([#72913](https://github.com/PostHog/posthog/pull/72913#discussion_r3637166337), [#58997](https://github.com/PostHog/posthog/pull/58997#discussion_r3273407591)).
- **Ship a new failure counter or fallback path with its alert, and label it with the workflow and the action.**
  Separate transient errors from real ones, so the alert neither stays silent nor pages on a blip ([#57847](https://github.com/PostHog/posthog/pull/57847#discussion_r3332195162), [#60447](https://github.com/PostHog/posthog/pull/60447#discussion_r3322712961)).

## Saving workflows

- **Validate workflows in the serializer, so API and MCP callers get the checks the UI has.**
  A save that the UI blocks but the API accepts gives an active workflow that never runs ([#117704](https://github.com/PostHog/posthog/pull/117704#discussion_r4292246554)).
- **Check a new validation rule against the workflows already saved, and accept the parts a save does not change.**
  A stricter rule otherwise makes existing workflows impossible to edit ([#63583](https://github.com/PostHog/posthog/pull/63583#discussion_r3422112444), [#83800](https://github.com/PostHog/posthog/pull/83800#discussion_r3853375781)).
- **Change a rule, an enum, or a list in every copy in the same PR, or derive one copy from the other.**
  The Python and Node sides, and the editor and the backend, drift otherwise, and a step works in one and fails in the other ([#88404](https://github.com/PostHog/posthog/pull/88404#discussion_r3866851998), [#114369](https://github.com/PostHog/posthog/pull/114369#discussion_r4259365228)).

## Secrets and data

- **Never write a masked secret back, and mask every secret input type wherever it is serialized.**
  That includes API responses, activity logs, revision snapshots, and HogVM output.
  A save of a masked value otherwise wipes the stored credential, and an unmasked one leaks into logs ([#72913](https://github.com/PostHog/posthog/pull/72913#discussion_r3637309317), [#83804](https://github.com/PostHog/posthog/pull/83804)).
- **Declare every custom DRF `@action` in `scope_object_read_actions` or `scope_object_write_actions`, with scopes that fit the data it returns.**
  Recipient emails are person data. An undeclared action is unreachable for API keys and MCP, or exposes data under too weak a scope ([#61001](https://github.com/PostHog/posthog/pull/61001#discussion_r3341676858), [#81483](https://github.com/PostHog/posthog/pull/81483)).
- **Capture events for a person with a distinct id, never with `person.id`.**
  `person.id` is the person UUID, and capturing with it creates a new, empty person ([#60647](https://github.com/PostHog/posthog/pull/60647)).
