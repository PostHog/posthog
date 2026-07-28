/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Create a bet in the drafted state.
 */
export const betsCreateBodySlugMax = 200

export const betsCreateBodySlugRegExp = new RegExp('^[-a-zA-Z0-9_]+$')
export const betsCreateBodyExecutionModeDefault = `external`
export const betsCreateBodyGateConfigOneChecksItemRequiredDefault = true
export const betsCreateBodyGateConfigOneArtifactOneTemplateDefault = `slim_base`

export const BetsCreateBody = /* @__PURE__ */ zod.object({
    slug: zod
        .string()
        .max(betsCreateBodySlugMax)
        .regex(betsCreateBodySlugRegExp)
        .describe("Unique-per-project identifier; also seeds the feature flag key ('bet-<slug>')."),
    hypothesis: zod.string().describe('The falsifiable statement this bet exists to test.'),
    success_metric: zod
        .object({
            name: zod.string().describe('Human-readable name of the metric the bet is judged on.'),
            target: zod
                .string()
                .optional()
                .describe(
                    "Target for the metric, e.g. '+10%' or '>= 0.42'. Free-form; the experiment carries the formal definition."
                ),
            description: zod.string().optional().describe('Optional longer description of how the metric is measured.'),
        })
        .describe('The single metric that decides whether the bet wins.'),
    guardrails: zod
        .array(
            zod.object({
                name: zod.string().describe('Name of the guardrail metric that must not regress.'),
                constraint: zod
                    .string()
                    .optional()
                    .describe("Constraint the guardrail enforces, e.g. 'error rate must not rise'."),
            })
        )
        .optional()
        .describe('Metrics that must not regress while the bet is exposed.'),
    budget: zod
        .object({
            usd: zod.number().optional().describe("Maximum spend for the bet's execution, in USD."),
            time_hours: zod.number().optional().describe('Wall-clock budget for the bet, in hours.'),
            iterations: zod.number().optional().describe('Maximum number of build iterations before the bet expires.'),
        })
        .optional()
        .describe('Resource ceiling for autonomous execution.'),
    exposure_plan: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('How the bet should be rolled out once gated (free-form, consumed by the orchestrator).'),
    sources: zod
        .array(
            zod.object({
                label: zod
                    .string()
                    .describe("Short label for the lineage source, e.g. 'signal: checkout error spike'."),
                url: zod.string().optional().describe('Link to the originating signal or report.'),
            })
        )
        .optional()
        .describe('Lineage references to the signals\/reports that motivated the bet.'),
    ttl: zod.iso.datetime({ offset: true }).nullish().describe('When the bet expires if unresolved.'),
    execution_mode: zod
        .enum(['external', 'managed'])
        .describe('\* `external` - external\n\* `managed` - managed')
        .default(betsCreateBodyExecutionModeDefault)
        .describe(
            "'external': any orchestrator POSTs events. 'managed': Foundry drives the run via Temporal.\n\n\* `external` - external\n\* `managed` - managed"
        ),
    run_config: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('Managed-mode execution config: {image\/template, command, env allowlist, caps}.'),
    memory_repo_url: zod
        .string()
        .nullish()
        .describe("Git-backed memory repo cloned into managed nodes' sandboxes at a conventional path."),
    gate_config: zod
        .object({
            checks: zod
                .array(
                    zod.object({
                        name: zod
                            .string()
                            .describe('Short identifier for this check, shown in the gate card breakdown.'),
                        check_type: zod
                            .enum(['command', 'coverage', 'mutation', 'flag_guard', 'reviewhog'])
                            .describe(
                                '\* `command` - command\n\* `coverage` - coverage\n\* `mutation` - mutation\n\* `flag_guard` - flag_guard\n\* `reviewhog` - reviewhog'
                            )
                            .describe(
                                "One of 'command', 'coverage', 'mutation', 'flag_guard', 'reviewhog'.\n\n\* `command` - command\n\* `coverage` - coverage\n\* `mutation` - mutation\n\* `flag_guard` - flag_guard\n\* `reviewhog` - reviewhog"
                            ),
                        required: zod
                            .boolean()
                            .default(betsCreateBodyGateConfigOneChecksItemRequiredDefault)
                            .describe(
                                "Required checks must pass for the gate to pass; a failing optional check is recorded in the breakdown but doesn't block gating."
                            ),
                        params: zod
                            .record(zod.string(), zod.unknown())
                            .optional()
                            .describe(
                                'Type-specific parameters; shape depends on check_type (see the per-type params serializers).'
                            ),
                    })
                )
                .optional()
                .describe(
                    'The constraint battery run against the artifact diff. Empty means no automatic gauntlet run.'
                ),
            protected_paths: zod
                .array(zod.string())
                .optional()
                .describe(
                    "Path prefixes the builder may never touch (e.g. the test-writer's acceptance tests). Non-empty implicitly adds an always-on, always-required 'protected_paths' check to the gate.result breakdown."
                ),
            artifact: zod
                .object({
                    template: zod
                        .enum(['default_base', 'notebook_base', 'pi_base', 'vm_base', 'streamlit_base', 'slim_base'])
                        .describe(
                            '\* `default_base` - default_base\n\* `notebook_base` - notebook_base\n\* `pi_base` - pi_base\n\* `vm_base` - vm_base\n\* `streamlit_base` - streamlit_base\n\* `slim_base` - slim_base'
                        )
                        .default(betsCreateBodyGateConfigOneArtifactOneTemplateDefault)
                        .describe(
                            'Sandbox template the gauntlet checks out the artifact and runs its checks in.\n\n\* `default_base` - default_base\n\* `notebook_base` - notebook_base\n\* `pi_base` - pi_base\n\* `vm_base` - vm_base\n\* `streamlit_base` - streamlit_base\n\* `slim_base` - slim_base'
                        ),
                })
                .optional()
                .describe('Sandbox config the gauntlet provisions to run checks in.'),
        })
        .optional()
        .describe("The gauntlet's constraint battery: checks, protected_paths, and artifact sandbox config."),
})

/**
 * Append a typed orchestrator event (run.started, node.spawned, gate.result, exposure.started, ...) and drive any state transition it implies. Events are immutable — there is no update or delete.
 */
export const BetsEventsCreateBody = /* @__PURE__ */ zod.object({
    kind: zod
        .enum([
            'run.started',
            'run.finished',
            'node.spawned',
            'node.finished',
            'node.failed',
            'artifact.ready',
            'gate.result',
            'exposure.started',
            'verdict.proposed',
            'budget.exceeded',
            'knowledge.published',
            'note',
        ])
        .describe(
            '\* `run.started` - run.started\n\* `run.finished` - run.finished\n\* `node.spawned` - node.spawned\n\* `node.finished` - node.finished\n\* `node.failed` - node.failed\n\* `artifact.ready` - artifact.ready\n\* `gate.result` - gate.result\n\* `exposure.started` - exposure.started\n\* `verdict.proposed` - verdict.proposed\n\* `budget.exceeded` - budget.exceeded\n\* `knowledge.published` - knowledge.published\n\* `note` - note'
        )
        .describe(
            "Typed event kind reported by the orchestrator. 'gate.result' with payload {pass: true} advances building → gated.\n\n\* `run.started` - run.started\n\* `run.finished` - run.finished\n\* `node.spawned` - node.spawned\n\* `node.finished` - node.finished\n\* `node.failed` - node.failed\n\* `artifact.ready` - artifact.ready\n\* `gate.result` - gate.result\n\* `exposure.started` - exposure.started\n\* `verdict.proposed` - verdict.proposed\n\* `budget.exceeded` - budget.exceeded\n\* `knowledge.published` - knowledge.published\n\* `note` - note"
        ),
    payload: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            "Event payload. For 'gate.result': {pass: bool, violations: [{code, message, severity}]}. Node\/knowledge\/artifact kinds (node.spawned, node.finished, node.failed, budget.exceeded, knowledge.published, artifact.ready) are validated against a typed shape."
        ),
})

/**
 * Record the market verdict on an exposed bet.
 */
export const BetsVerdictCreateBody = /* @__PURE__ */ zod.object({
    verdict: zod
        .enum(['promoted', 'rolled_back', 'iterate'])
        .describe('\* `promoted` - promoted\n\* `rolled_back` - rolled_back\n\* `iterate` - iterate')
        .describe(
            "'promoted' or 'rolled_back' archives the bet; 'iterate' sends it back to building with an incremented iteration counter.\n\n\* `promoted` - promoted\n\* `rolled_back` - rolled_back\n\* `iterate` - iterate"
        ),
})
