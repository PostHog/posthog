/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * How the bet should be rolled out once gated (free-form, consumed by the orchestrator).
 */
export type BetDTOApiExposurePlan = { [key: string]: unknown }

export interface SuccessMetricApi {
    /** Human-readable name of the metric the bet is judged on. */
    name: string
    /** Target for the metric, e.g. '+10%' or '>= 0.42'. Free-form; the experiment carries the formal definition. */
    target?: string
    /** Optional longer description of how the metric is measured. */
    description?: string
}

export interface GuardrailApi {
    /** Name of the guardrail metric that must not regress. */
    name: string
    /** Constraint the guardrail enforces, e.g. 'error rate must not rise'. */
    constraint?: string
}

export interface BudgetApi {
    /** Maximum spend for the bet's execution, in USD. */
    usd?: number
    /** Wall-clock budget for the bet, in hours. */
    time_hours?: number
    /** Maximum number of build iterations before the bet expires. */
    iterations?: number
}

export interface SourceRefApi {
    /** Short label for the lineage source, e.g. 'signal: checkout error spike'. */
    label: string
    /** Link to the originating signal or report. */
    url?: string
}

/**
 * * `external` - external
 * * `managed` - managed
 */
export type ExecutionModeEnumApi = (typeof ExecutionModeEnumApi)[keyof typeof ExecutionModeEnumApi]

export const ExecutionModeEnumApi = {
    External: 'external',
    Managed: 'managed',
} as const

export interface BuildLoopTargetRepoApi {
    /** Git URL of the repo the build loop checks out, commits to, and pushes — the tokened https form (credentials embedded, like memory_repo_url) when the repo requires auth to clone or push. */
    url: string
    /** Ref the test-writer (or the builder, when there's no test-writer) starts from. */
    base_ref: string
}

/**
 * Extra env vars for this node (e.g. an agent API key), merged under Foundry's own FOUNDRY_* protocol vars.
 */
export type BuildLoopNodeConfigApiEnv = { [key: string]: unknown }

export interface BuildLoopNodeConfigApi {
    /** Shell command that runs the coding agent for this role (e.g. 'claude -p "$(cat prompt.md)" --dangerously-skip-permissions'). Bet-specific details (hypothesis, success metric, protected paths, branch names, prior gate violations) arrive via FOUNDRY_* env vars, not text substitution — see references/build-loop.md. */
    command: string
    /** Extra env vars for this node (e.g. an agent API key), merged under Foundry's own FOUNDRY_* protocol vars. */
    env?: BuildLoopNodeConfigApiEnv
}

export interface BuildLoopConfigApi {
    /** The repo the test-writer/builder check out, commit to, and push. */
    target_repo: BuildLoopTargetRepoApi
    /** Optional pre-build node that writes acceptance tests under gate_config.protected_paths and pushes them to an immutable 'bet/<slug>-tests' baseline before the builder runs. Omit to skip test-writer separation (the builder then starts straight from target_repo.base_ref). */
    test_writer?: BuildLoopNodeConfigApi | null
    /** The node that implements the change behind the bet's flag and reports artifact.ready. */
    builder: BuildLoopNodeConfigApi
    /**
     * Caps builder retries on gate failure. Defaults to budget.iterations, or 3 if that's unset too.
     * @minimum 1
     * @nullable
     */
    max_gate_iterations?: number | null
}

/**
 * Env vars for the root managed node (e.g. an agent API key).
 */
export type RunConfigApiEnv = { [key: string]: unknown }

/**
 * Recursive-spawn caps for the root managed node: {max_depth, max_children, max_cost}. Ignored when build_loop is set.
 */
export type RunConfigApiCaps = { [key: string]: unknown }

export interface RunConfigApi {
    /** Shell command the root managed node runs. Ignored when build_loop is set. */
    command?: string
    /** Env vars for the root managed node (e.g. an agent API key). */
    env?: RunConfigApiEnv
    /** Recursive-spawn caps for the root managed node: {max_depth, max_children, max_cost}. Ignored when build_loop is set. */
    caps?: RunConfigApiCaps
    /** Runs a real coding agent (test-writer, then a bounded builder-retry loop against the gauntlet) instead of the plain scripted root node. See references/build-loop.md. */
    build_loop?: BuildLoopConfigApi | null
}

/**
 * * `command` - command
 * * `coverage` - coverage
 * * `mutation` - mutation
 * * `flag_guard` - flag_guard
 * * `reviewhog` - reviewhog
 */
export type CheckTypeEnumApi = (typeof CheckTypeEnumApi)[keyof typeof CheckTypeEnumApi]

export const CheckTypeEnumApi = {
    Command: 'command',
    Coverage: 'coverage',
    Mutation: 'mutation',
    FlagGuard: 'flag_guard',
    Reviewhog: 'reviewhog',
} as const

/**
 * Type-specific parameters; shape depends on check_type (see the per-type params serializers).
 */
export type GateCheckApiParams = { [key: string]: unknown }

export interface GateCheckApi {
    /** Short identifier for this check, shown in the gate card breakdown. */
    name: string
    /** One of 'command', 'coverage', 'mutation', 'flag_guard', 'reviewhog'.
     *
     * * `command` - command
     * * `coverage` - coverage
     * * `mutation` - mutation
     * * `flag_guard` - flag_guard
     * * `reviewhog` - reviewhog */
    check_type: CheckTypeEnumApi
    /** Required checks must pass for the gate to pass; a failing optional check is recorded in the breakdown but doesn't block gating. */
    required?: boolean
    /** Type-specific parameters; shape depends on check_type (see the per-type params serializers). */
    params?: GateCheckApiParams
}

/**
 * * `default_base` - default_base
 * * `notebook_base` - notebook_base
 * * `pi_base` - pi_base
 * * `vm_base` - vm_base
 * * `streamlit_base` - streamlit_base
 * * `slim_base` - slim_base
 */
export type TemplateEnumApi = (typeof TemplateEnumApi)[keyof typeof TemplateEnumApi]

export const TemplateEnumApi = {
    DefaultBase: 'default_base',
    NotebookBase: 'notebook_base',
    PiBase: 'pi_base',
    VmBase: 'vm_base',
    StreamlitBase: 'streamlit_base',
    SlimBase: 'slim_base',
} as const

export interface GateArtifactConfigApi {
    /** Sandbox template the gauntlet checks out the artifact and runs its checks in.
     *
     * * `default_base` - default_base
     * * `notebook_base` - notebook_base
     * * `pi_base` - pi_base
     * * `vm_base` - vm_base
     * * `streamlit_base` - streamlit_base
     * * `slim_base` - slim_base */
    template?: TemplateEnumApi
}

export interface GateConfigApi {
    /** The constraint battery run against the artifact diff. Empty means no automatic gauntlet run. */
    checks?: GateCheckApi[]
    /** Path prefixes the builder may never touch (e.g. the test-writer's acceptance tests). Non-empty implicitly adds an always-on, always-required 'protected_paths' check to the gate.result breakdown. */
    protected_paths?: string[]
    /** Sandbox config the gauntlet provisions to run checks in. */
    artifact?: GateArtifactConfigApi
}

/**
 * * `drafted` - DRAFTED
 * * `funded` - FUNDED
 * * `building` - BUILDING
 * * `gated` - GATED
 * * `exposed` - EXPOSED
 * * `archived` - ARCHIVED
 */
export type BetDTOStateEnumApi = (typeof BetDTOStateEnumApi)[keyof typeof BetDTOStateEnumApi]

export const BetDTOStateEnumApi = {
    Drafted: 'drafted',
    Funded: 'funded',
    Building: 'building',
    Gated: 'gated',
    Exposed: 'exposed',
    Archived: 'archived',
} as const

/**
 * * `promoted` - PROMOTED
 * * `rolled_back` - ROLLED_BACK
 * * `iterate` - ITERATE
 */
export type BetDTOVerdictEnumApi = (typeof BetDTOVerdictEnumApi)[keyof typeof BetDTOVerdictEnumApi]

export const BetDTOVerdictEnumApi = {
    Promoted: 'promoted',
    RolledBack: 'rolled_back',
    Iterate: 'iterate',
} as const

export interface BetDTOApi {
    /** The single metric that decides whether the bet wins. */
    success_metric: SuccessMetricApi
    /** Metrics that must not regress while the bet is exposed. */
    guardrails: GuardrailApi[]
    /** Resource ceiling for autonomous execution. */
    budget: BudgetApi
    /** How the bet should be rolled out once gated (free-form, consumed by the orchestrator). */
    exposure_plan: BetDTOApiExposurePlan
    /** Lineage references to the signals/reports that motivated the bet. */
    sources: SourceRefApi[]
    /** 'external': any orchestrator POSTs events. 'managed': Foundry drives the run via Temporal.
     *
     * * `external` - external
     * * `managed` - managed */
    execution_mode: ExecutionModeEnumApi
    /** Managed-mode execution config: {command, env, caps} for a plain root node, or {build_loop} for a real-agent build loop. */
    run_config: RunConfigApi
    /**
     * Git-backed memory repo cloned into managed nodes' sandboxes at a conventional path.
     * @nullable
     */
    memory_repo_url?: string | null
    /** The gauntlet's constraint battery: checks, protected_paths, and artifact sandbox config. */
    gate_config: GateConfigApi
    id: string
    slug: string
    hypothesis: string
    /** @nullable */
    ttl: string | null
    state: BetDTOStateEnumApi
    verdict: BetDTOVerdictEnumApi | null
    iteration: number
    /** @nullable */
    feature_flag_id: number | null
    /** @nullable */
    feature_flag_key: string | null
    /** @nullable */
    experiment_id: number | null
    /** @nullable */
    created_by_id: number | null
    created_at: string
    updated_at: string
}

/**
 * How the bet should be rolled out once gated (free-form, consumed by the orchestrator).
 */
export type CreateBetApiExposurePlan = { [key: string]: unknown }

export interface CreateBetApi {
    /**
     * Unique-per-project identifier; also seeds the feature flag key ('bet-<slug>').
     * @maxLength 200
     * @pattern ^[-a-zA-Z0-9_]+$
     */
    slug: string
    /** The falsifiable statement this bet exists to test. */
    hypothesis: string
    /** The single metric that decides whether the bet wins. */
    success_metric: SuccessMetricApi
    /** Metrics that must not regress while the bet is exposed. */
    guardrails?: GuardrailApi[]
    /** Resource ceiling for autonomous execution. */
    budget?: BudgetApi
    /** How the bet should be rolled out once gated (free-form, consumed by the orchestrator). */
    exposure_plan?: CreateBetApiExposurePlan
    /** Lineage references to the signals/reports that motivated the bet. */
    sources?: SourceRefApi[]
    /**
     * When the bet expires if unresolved.
     * @nullable
     */
    ttl?: string | null
    /** 'external': any orchestrator POSTs events. 'managed': Foundry drives the run via Temporal.
     *
     * * `external` - external
     * * `managed` - managed */
    execution_mode?: ExecutionModeEnumApi
    /** Managed-mode execution config: {command, env, caps} for a plain root node, or {build_loop} for a real-agent build loop. */
    run_config?: RunConfigApi
    /**
     * Git-backed memory repo cloned into managed nodes' sandboxes at a conventional path.
     * @nullable
     */
    memory_repo_url?: string | null
    /** The gauntlet's constraint battery: checks, protected_paths, and artifact sandbox config. */
    gate_config?: GateConfigApi
}

/**
 * Event payload as reported by the orchestrator.
 */
export type BetEventDTOApiPayload = { [key: string]: unknown }

/**
 * * `run.started` - RUN_STARTED
 * * `run.finished` - RUN_FINISHED
 * * `node.spawned` - NODE_SPAWNED
 * * `node.finished` - NODE_FINISHED
 * * `node.failed` - NODE_FAILED
 * * `artifact.ready` - ARTIFACT_READY
 * * `gate.result` - GATE_RESULT
 * * `exposure.started` - EXPOSURE_STARTED
 * * `verdict.proposed` - VERDICT_PROPOSED
 * * `budget.exceeded` - BUDGET_EXCEEDED
 * * `knowledge.published` - KNOWLEDGE_PUBLISHED
 * * `note` - NOTE
 * * `state.changed` - STATE_CHANGED
 */
export type BetEventDTOKindEnumApi = (typeof BetEventDTOKindEnumApi)[keyof typeof BetEventDTOKindEnumApi]

export const BetEventDTOKindEnumApi = {
    Runstarted: 'run.started',
    Runfinished: 'run.finished',
    Nodespawned: 'node.spawned',
    Nodefinished: 'node.finished',
    Nodefailed: 'node.failed',
    Artifactready: 'artifact.ready',
    Gateresult: 'gate.result',
    Exposurestarted: 'exposure.started',
    Verdictproposed: 'verdict.proposed',
    Budgetexceeded: 'budget.exceeded',
    Knowledgepublished: 'knowledge.published',
    Note: 'note',
    Statechanged: 'state.changed',
} as const

export interface BetEventDTOApi {
    /** Event payload as reported by the orchestrator. */
    payload: BetEventDTOApiPayload
    id: string
    bet_id: string
    kind: BetEventDTOKindEnumApi
    created_at: string
}

/**
 * Event payload. For 'gate.result': {pass: bool, violations: [{code, message, severity}]}. Node/knowledge/artifact kinds (node.spawned, node.finished, node.failed, budget.exceeded, knowledge.published, artifact.ready) are validated against a typed shape.
 */
export type CreateBetEventApiPayload = { [key: string]: unknown }

/**
 * * `run.started` - run.started
 * * `run.finished` - run.finished
 * * `node.spawned` - node.spawned
 * * `node.finished` - node.finished
 * * `node.failed` - node.failed
 * * `artifact.ready` - artifact.ready
 * * `gate.result` - gate.result
 * * `exposure.started` - exposure.started
 * * `verdict.proposed` - verdict.proposed
 * * `budget.exceeded` - budget.exceeded
 * * `knowledge.published` - knowledge.published
 * * `note` - note
 */
export type CreateBetEventKindEnumApi = (typeof CreateBetEventKindEnumApi)[keyof typeof CreateBetEventKindEnumApi]

export const CreateBetEventKindEnumApi = {
    Runstarted: 'run.started',
    Runfinished: 'run.finished',
    Nodespawned: 'node.spawned',
    Nodefinished: 'node.finished',
    Nodefailed: 'node.failed',
    Artifactready: 'artifact.ready',
    Gateresult: 'gate.result',
    Exposurestarted: 'exposure.started',
    Verdictproposed: 'verdict.proposed',
    Budgetexceeded: 'budget.exceeded',
    Knowledgepublished: 'knowledge.published',
    Note: 'note',
} as const

export interface CreateBetEventApi {
    /** Typed event kind reported by the orchestrator. 'gate.result' with payload {pass: true} advances building → gated.
     *
     * * `run.started` - run.started
     * * `run.finished` - run.finished
     * * `node.spawned` - node.spawned
     * * `node.finished` - node.finished
     * * `node.failed` - node.failed
     * * `artifact.ready` - artifact.ready
     * * `gate.result` - gate.result
     * * `exposure.started` - exposure.started
     * * `verdict.proposed` - verdict.proposed
     * * `budget.exceeded` - budget.exceeded
     * * `knowledge.published` - knowledge.published
     * * `note` - note */
    kind: CreateBetEventKindEnumApi
    /** Event payload. For 'gate.result': {pass: bool, violations: [{code, message, severity}]}. Node/knowledge/artifact kinds (node.spawned, node.finished, node.failed, budget.exceeded, knowledge.published, artifact.ready) are validated against a typed shape. */
    payload?: CreateBetEventApiPayload
}

/**
 * * `spawned` - SPAWNED
 * * `running` - RUNNING
 * * `finished` - FINISHED
 * * `failed` - FAILED
 * * `cancelled` - CANCELLED
 */
export type BetNodeDTOStatusEnumApi = (typeof BetNodeDTOStatusEnumApi)[keyof typeof BetNodeDTOStatusEnumApi]

export const BetNodeDTOStatusEnumApi = {
    Spawned: 'spawned',
    Running: 'running',
    Finished: 'finished',
    Failed: 'failed',
    Cancelled: 'cancelled',
} as const

export interface BetNodeDTOApi {
    id: string
    bet_id: string
    /** @nullable */
    parent_id: string | null
    node_id: string
    status: BetNodeDTOStatusEnumApi
    runner: string
    depth: number
    /** @nullable */
    max_cost: number | null
    /** @nullable */
    max_depth: number | null
    /** @nullable */
    max_children: number | null
    cost_so_far: number
    /** @nullable */
    sandbox_external_id: string | null
    created_at: string
    updated_at: string
}

/**
 * * `promoted` - promoted
 * * `rolled_back` - rolled_back
 * * `iterate` - iterate
 */
export type RecordVerdictVerdictEnumApi = (typeof RecordVerdictVerdictEnumApi)[keyof typeof RecordVerdictVerdictEnumApi]

export const RecordVerdictVerdictEnumApi = {
    Promoted: 'promoted',
    RolledBack: 'rolled_back',
    Iterate: 'iterate',
} as const

export interface RecordVerdictApi {
    /** 'promoted' or 'rolled_back' archives the bet; 'iterate' sends it back to building with an incremented iteration counter.
     *
     * * `promoted` - promoted
     * * `rolled_back` - rolled_back
     * * `iterate` - iterate */
    verdict: RecordVerdictVerdictEnumApi
}
