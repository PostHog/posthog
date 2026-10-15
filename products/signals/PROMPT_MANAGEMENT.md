# Managed decision prompts and wording trials

The actionability, signal-safety, and report-safety gates keep Sonnet on their bundled policies.
In `system-one-shadow` mode, one Jeeves call compares against that baseline. Managed policies,
questions, and thresholds apply only to the System One input; team actionability steering applies
to both inputs. The existing mode flag continues to control which provider decides.

Prompt reads use `SIGNALS_PROMPT_PERSONAL_API_KEY`, separate from the shared analytics/flag SDK
credential and `AI_GATEWAY_API_KEY`. Give this personal key only `llm_prompt:read` and restrict it
to the prompt-library project. Configure that project's public token as
`SIGNALS_PROMPT_PROJECT_API_KEY` and its app host as `SIGNALS_PROMPT_HOST` (default
`https://us.posthog.com`). Use a distinct credential per environment. Without these settings,
or when a managed version is unreadable or invalid, the gate uses its bundled Jeeves settings.

Activate managed reads without changing decisions:

1. Run `uv run manage.py export_signals_decision_prompts --include-wording-experiments`.
   The command exports policies and config from the same defaults the gates use; it makes no writes.
2. Publish each `control` entry as a new version of its named prompt and assign `signals-production`
   to that version. This fresh label deliberately ignores existing `production` labels, whose
   policies, models, and thresholds may differ from the bundled defaults. Publish trial entries
   without that label. The trials vary only the yes/no question and preserve model, policy, and threshold.
3. Verify with `uv run manage.py export_signals_decision_prompts --verify-managed` in an environment
   configured with the reader settings before rolling those settings out to workers. It fails if
   any control is missing, unreadable, or differs from bundled settings.
4. Check comparison events for `system_one_prompt_source=managed` and the expected `$ai_prompt_version`.
   Workers refresh asynchronously every minute, returning the bundled prompt during initial loading.

After activation, editing a prompt creates an immutable version; move `signals-production` when
the change should apply to the normal Jeeves shadow. Sonnet's policy remains fixed.

For an A/B wording trial, create a multivariate flag named `signals-system-one-shadow-prompt`.
Each variant's JSON payload is `{"prompt_versions": {"<prompt-name>": <version>}}`.
Pin the control and trial versions explicitly; the flag's allocation sets the traffic split.
Assignment uses the decision ID, so each call chooses one version rather than making multiple
shadow calls. A missing mapping, unavailable version, invalid config, or flag error retains the
normal prompt. Only Jeeves versions are accepted. Private report trials continue to use the
traditional-only path. Oversized report shadow inputs skip Jeeves rather than truncate signals.

Compare `system_one_prompt_experiment_variant`, `system_one_prompt_experiment_status`, prompt
version, stage, probability, threshold, and disagreement on `signals_typesafe_decision_evaluated`.
Signal-safety verdict caching is bypassed in shadow mode so a previous verdict cannot suppress
assignment and comparison. Disable the wording flag to return to the normal managed prompt;
remove reader settings to return to bundled settings.
