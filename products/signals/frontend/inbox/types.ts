import type { UserBasicType } from '~/types'

import {
    type ReportChartApi,
    type SignalReportRefundApi,
    type SignalScoutRunSummaryApi,
    SignalSourceProductApi as SignalSourceProduct,
    SignalSourceTypeApi as SignalSourceType,
} from 'products/signals/frontend/generated/api.schemas'

// The canonical signal taxonomy, generated from the backend enums via OpenAPI/Orval.
// Re-exported under the domain names so consumers don't carry the `Api` suffix around.
export { SignalSourceProduct, SignalSourceType }

// Suggested-reviewer shapes, read from `suggested_reviewers` artefact content (a polymorphic JSON
// field with no per-type OpenAPI schema). Mirrors EnrichedReviewer/RelevantCommit in
// products/signals/backend/contracts.py.
export interface RelevantCommit {
    sha: string
    url: string
    reason: string
}

export interface SignalReviewerUserInfo {
    id: number
    uuid: string
    first_name: string
    last_name: string
    email: string
}

export interface EnrichedReviewer {
    github_login: string
    github_name: string | null
    relevant_commits: RelevantCommit[]
    user: SignalReviewerUserInfo | null
    /** Why this reviewer was chosen. Absent on artefacts stored before the field existed. */
    reason?: string | null
}

/** P0 (highest) – P4 (lowest). Mirrors desktop `SignalReportPriority`. */
export type SignalReportPriority = 'P0' | 'P1' | 'P2' | 'P3' | 'P4'

/** Threshold options over SignalReportPriority, strictest first. Shared by the auto-start and Slack min-priority selects. */
export const PRIORITY_THRESHOLD_OPTIONS: { value: SignalReportPriority; label: string }[] = [
    { value: 'P0', label: 'P0 only' },
    { value: 'P1', label: 'P1 and above' },
    { value: 'P2', label: 'P2 and above' },
    { value: 'P3', label: 'P3 and above' },
    { value: 'P4', label: 'P4 and above' },
]

/** Actionability judgment outcome. Mirrors desktop `SignalReportActionability`. */
export type SignalReportActionability = 'immediately_actionable' | 'requires_human_input' | 'not_actionable'

/** Actionability values that represent a report worth acting on — drives the Reports tab filter and the Create PR gate. */
export const ACTIONABLE_ACTIONABILITY_VALUES: SignalReportActionability[] = [
    'immediately_actionable',
    'requires_human_input',
]

export interface SignalReport {
    id: string
    title: string | null
    summary: string | null
    status: SignalReportStatus
    total_weight: number
    signal_count: number
    relevant_user_count: number | null
    created_at: string
    updated_at: string
    artefact_count: number
    is_suggested_reviewer: boolean
    /** Charts the report shows, placed by `[label](chart:<chart_id>)` links in the summary. */
    charts?: ReportChartApi[]
    /** Questions the report's author suggests asking about it, offered above the "Ask AI" box. */
    suggested_prompts?: string[]
    /** Count of signals at the time the latest research run kicked off. */
    signals_at_run?: number
    /** P0–P4 from the priority judgment when the report is researched. */
    priority?: SignalReportPriority | null
    /** Actionability choice from the actionability judgment artefact. */
    actionability?: SignalReportActionability | null
    /** Whether the issue is already being handled — fixed in recent changes, or with a fix in flight (an open PR, a recently active branch, an assigned / in-progress issue or agent task) — from the actionability judgment artefact. */
    already_addressed?: boolean | null
    /** Distinct source products contributing signals to this report. */
    source_products?: string[]
    /** skill_name slug of the authoring scout, when scout-authored (raw slug — prettify with `scoutDisplayName`). */
    scout_name?: string | null
    /** PR URL from the latest implementation task run, if available. */
    implementation_pr_url?: string | null
    /** Whether that implementation PR is merged, per the GitHub webhook. Status doesn't imply it: a
     * resolved report may have been resolved directly, without a merged PR. */
    implementation_pr_merged?: boolean
    /** Reason code from the latest dismissal artefact (when archived). See dismissalReasons. */
    dismissal_reason?: string | null
    /** Free-form note from the latest dismissal artefact (when archived). */
    dismissal_note?: string | null
    /** The report's PR refund, when one exists (one refund per report, ever). */
    refund?: SignalReportRefundApi | null
    /** Non-null when the report is system-marked never-billable (PostHog-system origin) — its PR is free. */
    billing_exempt_reason?: string | null
    /** Backend-owned refund eligibility: why a refund would be rejected right now, null when it would be accepted. */
    refund_ineligibility_reason?: string | null
}

export enum SignalReportStatus {
    POTENTIAL = 'potential',
    CANDIDATE = 'candidate',
    IN_PROGRESS = 'in_progress',
    PENDING_INPUT = 'pending_input',
    READY = 'ready',
    RESOLVED = 'resolved',
    FAILED = 'failed',
    // Out-of-inbox terminal states (backend: SignalReport.Status). Excluded from every tab.
    DELETED = 'deleted',
    SUPPRESSED = 'suppressed',
}

export interface SignalReportArtefact {
    id: string
    type: string
    content: Record<string, any>
    created_at: string
    /** Log artefacts are editable in place; null for write-once rows. */
    updated_at?: string | null
    /** Set when a human produced the artefact (drives the "by {name}" attribution byline). */
    created_by?: UserBasicType | null
    /** Set when an agent task produced the artefact (attribution reads "by agent"). */
    task_id?: string | null
}

export interface SignalReportArtefactResponse {
    results: SignalReportArtefact[]
    count: number
}

export interface SignalSourceConfig {
    id: string
    source_product: SignalSourceProduct
    source_type: SignalSourceType
    enabled: boolean
    config: Record<string, any>
    created_at: string
    updated_at: string
    status: SignalSourceConfigStatus | null
}

export interface ToggleSignalSourceParams {
    sourceProduct: SignalSourceProduct
    sourceType: SignalSourceType
    enabled: boolean
    config?: Record<string, any>
    /** True when the enable came through the data-warehouse setup wizard, for `Signal source connected`. */
    viaSetupWizard?: boolean
}

export enum SignalSourceConfigStatus {
    RUNNING = 'running',
    COMPLETED = 'completed',
    FAILED = 'failed',
}

// `SignalSourceConfig.config` keys the emission actionability gate reads. Mirrors
// STEERING_KEY / DEFAULT_NOT_ACTIONABLE_KEY / STEERING_MAX_LENGTH in
// products/signals/backend/contracts.py; the generated config type is an open object,
// so the key names and cap only exist here and there.
export const SOURCE_STEERING_KEY = 'steering'
export const SOURCE_DEFAULT_NOT_ACTIONABLE_KEY = 'default_not_actionable'
export const SOURCE_STEERING_MAX_LENGTH = 2000

// ── Inbox IA: page tabs, report sections, scope ──────────────────────────────

/**
 * The inbox's page-level tabs. Each is a URL segment (`/inbox/<tab>`), so the keys are pinned.
 * The union covers both inbox layouts: the redesign (`INBOX_TAB_KEYS`, behind
 * `FEATURE_FLAGS.INBOX_REDESIGN`) and the layout it replaces (`INBOX_LEGACY_TAB_KEYS`). Each
 * layout redirects the other's segments (see `inboxTabRedirectPath`), so a link made under one
 * layout still opens under the other.
 */
export type InboxTabKey =
    | 'reports'
    | 'scouts'
    | 'settings'
    | 'pulls'
    | 'not-actionable'
    | 'runs'
    | 'archived'
    | 'config'

/** The redesign's page tabs. */
export const INBOX_TAB_KEYS: InboxTabKey[] = ['reports', 'scouts', 'settings']

/** The page tabs with the redesign flag off: one tab per report list, plus Runs and Configuration. */
export const INBOX_LEGACY_TAB_KEYS: InboxTabKey[] = [
    'pulls',
    'reports',
    'scouts',
    'not-actionable',
    'runs',
    'archived',
    'config',
]

export const INBOX_TAB_LABEL: Record<InboxTabKey, string> = {
    reports: 'Reports',
    scouts: 'Scouts',
    settings: 'Settings',
    pulls: 'Pull requests',
    'not-actionable': 'Not actionable',
    runs: 'Runs',
    archived: 'Archive',
    config: 'Configuration',
}

/** What each tab holds, surfaced as the scene description while that tab is active so new users can orient themselves. */
export const INBOX_TAB_DESCRIPTION: Record<InboxTabKey, string> = {
    reports: 'Issues and opportunities found in your product, ready to review.',
    scouts: 'Scheduled agents that sweep this project and file what they find.',
    settings: 'Signal sources, PR generation, code access, and notifications.',
    pulls: 'Pull requests agents opened to resolve reports. Review and merge them on GitHub.',
    'not-actionable':
        'Reports judged not actionable because they are too vague, lack supporting evidence, or describe expected behavior.',
    runs: 'Project-wide list of agent runs, for debugging.',
    archived: 'Reports you archived. You can restore them to the inbox at any time.',
    config: 'Set up signal sources, scouts, and how autonomously agents can act.',
}

/** With the redesign flag off, the Reports tab is only the researched reports, and its description says so. */
export const INBOX_LEGACY_TAB_DESCRIPTION: Record<InboxTabKey, string> = {
    ...INBOX_TAB_DESCRIPTION,
    reports: 'Issues and opportunities agents found in your product data, researched and prioritized for your review.',
}

/**
 * The sections of the Reports list, in render order: work waiting on you first, then work waiting
 * on an agent. Each is a collapsible run of report cards with
 * its own fixed server filter (see `INBOX_REPORT_SECTION_LIST_PARAMS`), keyed `reportListLogic`
 * instance, header count, and pagination — the sections stack in one column rather than switching.
 * pinned: these keys are the `tab` property on the inbox analytics events, the `data-attr` on each
 * section header, and the keys of the persisted expanded/collapsed state, so they outlive renames of
 * the labels above them (`needs-decision` is now "Needs a PR", `monitoring` is "Review and merge").
 */
export const INBOX_REPORT_SECTION_KEYS = ['monitoring', 'needs-decision', 'resolved', 'not-actionable'] as const
export type InboxReportSectionKey = (typeof INBOX_REPORT_SECTION_KEYS)[number]

/**
 * The section the inbox is fundamentally about: what triage mode walks, and the one whose For-you
 * count decides the default scope.
 */
export const INBOX_PRIMARY_REPORT_SECTION_KEY: InboxReportSectionKey = 'needs-decision'

export const INBOX_REPORT_SECTION_LABEL: Record<InboxReportSectionKey, string> = {
    monitoring: 'Review and merge',
    'needs-decision': 'Needs a PR',
    resolved: 'Resolved',
    'not-actionable': 'Not actionable',
}

/** One line per section, shown under its header while the section is open. */
export const INBOX_REPORT_SECTION_DESCRIPTION: Record<InboxReportSectionKey, string> = {
    monitoring: 'Reports with a pull request open, ready for you to review and merge on GitHub.',
    'needs-decision': 'Reports an agent can act on that have no pull request yet.',
    resolved: 'Reports resolved by a merged pull request, and reports you archived.',
    'not-actionable':
        'Reports judged not actionable because they are too vague, lack supporting evidence, or describe expected behavior.',
}

/**
 * Sections only rendered for staff users (internal). Not actionable is an internal triage surface;
 * every other section is public to any team member.
 */
export const INBOX_STAFF_ONLY_REPORT_SECTION_KEYS: InboxReportSectionKey[] = ['not-actionable']

/** Small tag rendered next to a section's label in its header. */
export const INBOX_REPORT_SECTION_TAG: Partial<Record<InboxReportSectionKey, 'Staff'>> = {
    'not-actionable': 'Staff',
}

// ── Legacy inbox IA (redesign flag off): one tab per report list ─────────────

/**
 * The Configuration tab holds the agent-setup widgets. It only appears when the scene is too
 * narrow for the right-hand setup rail (see `AgentSetupColumn`); on wide viewports the rail
 * replaces it. Kept a real routing key so deep links and narrow-mode navigation work.
 */
export const INBOX_CONFIG_TAB_KEY: InboxTabKey = 'config'

/** Tabs only visible to staff users (internal), mirroring `INBOX_STAFF_ONLY_REPORT_SECTION_KEYS`. */
export const INBOX_STAFF_ONLY_TAB_KEYS: InboxTabKey[] = ['not-actionable']

/** Small tag rendered next to a tab's label in the tab bar. */
export const INBOX_TAB_TAG: Partial<Record<InboxTabKey, 'Staff' | 'Alpha'>> = {
    'not-actionable': 'Staff',
}

/** The flat report-list tabs that share the keyed `reportListLogic` + `InboxReportList` primitive. */
export const INBOX_FLAT_LIST_TAB_KEYS = ['pulls', 'reports', 'not-actionable', 'archived'] as const
export type InboxFlatListTabKey = (typeof INBOX_FLAT_LIST_TAB_KEYS)[number]

/**
 * Each legacy report tab shows exactly one of the redesign's sections, with the same server filter.
 * Both layouts share the keyed `reportListLogic` instances through this map, so a report loaded
 * under one layout is found by the other and the mount-time count loaders are not duplicated.
 */
export const INBOX_LEGACY_TAB_SECTION: Record<InboxFlatListTabKey, InboxReportSectionKey> = {
    pulls: 'monitoring',
    reports: 'needs-decision',
    'not-actionable': 'not-actionable',
    archived: 'resolved',
}

/** The inverse of `INBOX_LEGACY_TAB_SECTION`: the legacy tab that lists a section's reports. */
export const INBOX_SECTION_LEGACY_TAB: Record<InboxReportSectionKey, InboxFlatListTabKey> = {
    monitoring: 'pulls',
    'needs-decision': 'reports',
    'not-actionable': 'not-actionable',
    resolved: 'archived',
}

/**
 * The legacy counterpart of `INBOX_PRIMARY_REPORT_SECTION_KEY`: the Pull requests tab is the one
 * whose For-you count decides the default scope with the flag off.
 */
export const INBOX_LEGACY_PRIMARY_REPORT_SECTION_KEY: InboxReportSectionKey = 'monitoring'

/** `for-you` (suggested-reviewer reports), `entire-project` (all), or `teammate:<uuid>`. */
export type InboxScope = 'for-you' | 'entire-project' | `teammate:${string}`

export const INBOX_SCOPE_FOR_YOU: InboxScope = 'for-you'
export const INBOX_SCOPE_ENTIRE_PROJECT: InboxScope = 'entire-project'

// ── SignalReport ↔ Task linkage ─────────────────────────────────────────────
// The task↔report association is the `task_run` artefact log (see artefactTypes.ts). The
// relationship vocabulary below is what a client may assert on the task-creation kickoff path via
// `signal_report_task_relationship`: `implementation` starts a PR run (and opens the auto-start
// spend gate), `discussion` links a discuss-the-report task. `research` is reserved for the
// server-side research pipeline and is rejected by the tasks API.

export const SIGNAL_REPORT_TASK_RELATIONSHIPS = ['implementation', 'discussion'] as const

export type SignalReportTaskRelationship = (typeof SIGNAL_REPORT_TASK_RELATIONSHIPS)[number]

export const SIGNAL_REPORT_TASK_IMPLEMENTATION_RELATIONSHIP: SignalReportTaskRelationship = 'implementation'

export const SIGNAL_REPORT_TASK_DISCUSSION_RELATIONSHIP: SignalReportTaskRelationship = 'discussion'

// ── Autonomy config (per-user override; backend SignalUserAutonomyConfigView) ─

export interface SignalUserAutonomyConfig {
    id?: string
    autostart_priority: SignalReportPriority | null
    slack_notification_integration_id?: number | null
    slack_notification_channel?: string | null
    slack_notification_min_priority?: SignalReportPriority | null
    created_at?: string
    updated_at?: string
}

// ── Team-level autonomy config (backend SignalTeamConfigViewSet; singleton per team) ─

export interface SignalTeamConfig {
    id?: string
    /** Master switch for autonomous inbox PRs. Only an explicit false disables auto-start; null (never set) leaves it on. */
    autostart_enabled?: boolean | null
    /** Team-wide default PR auto-start threshold (P0–P4, non-null from the API). "Never" is expressed via autostart_enabled instead. */
    default_autostart_priority: SignalReportPriority | null
    /** Default Slack channel for this team's inbox notifications. */
    default_slack_notification_channel?: string | null
    /** Per-repo base-branch overrides for auto-started PRs, keyed by 'org/repo'. */
    autostart_base_branches?: Record<string, string>
    /** Daily cap on new reports surfacing to the inbox (project-timezone day). Null means unlimited. */
    max_reports_per_day?: number | null
    /** Read-only: reports that first became visible today (project timezone). Never send in a patch. */
    reports_generated_today?: number
    /** Read-only: whether the daily report limit is reached, pausing new report generation until local midnight. Never send in a patch. */
    daily_report_limit_reached?: boolean
    created_at?: string
    updated_at?: string
}

// ── Runs (composed client-side from scout runs + signal-pipeline tasks) ───────

/** Whether a run-shaped task came from a headless scout or the signals pipeline. */
export type SignalRunKind = 'scout' | 'signal'

/**
 * One row in the Runs tab. Not a backend resource — `inboxSceneLogic` composes these from two
 * existing endpoints: scout runs (`signals/scout/runs`, kind `scout`) and signal-pipeline tasks
 * (`tasks?origin_product=signal_report`, kind `signal`), merged newest-first. Rows link out to the
 * standalone Tasks scene (`/tasks/{task_id}`).
 */
export interface SignalRun {
    task_id: string
    kind: SignalRunKind
    /** Scout: the `signals-scout-*` skill code name (shown verbatim). Signal: the report title. */
    title: string
    /** Latest run status, or null if unknown. Shares `TaskRunStatus` values. */
    status: SignalScoutRunStatus | null
    /** Signal runs: the inbox report this run belongs to, for linking to it. Null for scouts. */
    report_id: string | null
    created_at: string
}

// ── Scouts (backend SignalScoutConfigViewSet / SignalScoutRunViewSet) ─────────

/** Status from the linked TaskRun behind a scout run. */
export type SignalScoutRunStatus = SignalScoutRunSummaryApi['status']

/** Lightweight projection of a scout run row (newest-first list response).
 * An interface extension (not a type alias) so kea-typegen keeps the domain name
 * instead of inlining `import(...)` references to the generated type. */
export interface SignalScoutRunSummary extends SignalScoutRunSummaryApi {}

/** One finding a scout run emitted to the inbox. */
export interface SignalScoutEmission {
    id: string
    run_id: string
    finding_id: string
    description: string
    weight: number
    confidence: number
    severity: SignalReportPriority | null
    /** Slug tags the scout attached to this finding (lowercase kebab-case, e.g. `cost-spike`). */
    tags: string[]
    source_id: string
    emitted_at: string
}

/** Minimal projection of the inbox report a scout finding grouped into (for the linked chip). */
export interface LinkedSignalReport {
    id: string
    title: string | null
}

/** One finding a run emitted, paired with the inbox report (if any) its signal grouped into. */
export interface SignalScoutEmissionReportLink {
    finding_id: string
    /** Deterministic `run:<run_id>:finding:<finding_id>` join key — the stable key into the emission set. */
    source_id: string
    /** The inbox report this finding linked to, or null if none could be resolved (not yet grouped, deduped, deleted). */
    report: LinkedSignalReport | null
}

// ── Report state transitions (backend `state` action: dismiss / snooze) ──────

export interface SignalReportStateRequest {
    state: 'suppressed' | 'potential'
    dismissal_reason?: string
    dismissal_note?: string
    /** Only honored for state === 'potential' (snooze): re-promote after N more signals. */
    snooze_for?: number
}
