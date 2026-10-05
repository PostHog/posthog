// Pure (no-React) artefact helpers shared by the detail logic and the activity-log renderers.
// Mirrors the PostHog Desktop inbox's artefact-log domain helpers. Content shapes stay loose
// (`Record<string, any>` on the artefact) and are read through these typed accessors so legacy
// rows with extra/missing keys never crash a render.

import { isObject } from 'lib/utils/guards'
import { identifierToHuman } from 'lib/utils/strings'

import { SignalReportArtefact } from '../../types'

/** Built-in signals pipeline product identifier on a `task_run` artefact. */
export const SIGNALS_PRODUCT = 'signals'

// ── Per-type content shapes (read defensively; treat every field as possibly absent) ─────────

export interface CodeReferenceContent {
    file_path: string
    start_line?: number
    end_line?: number
    contents?: string
    relevance_note?: string
}

export interface LineReferenceContent {
    file_path: string
    line?: number
    note?: string
    contents?: string
}

export interface CommitContent {
    repository: string
    branch: string
    commit_sha: string
    message: string
    note?: string
}

export interface TaskRunArtefactContent {
    task_id: string
    run_id?: string | null
    product: string
    type: string
}

export interface NoteContent {
    note: string
    author?: string
}

export interface SignalFindingContent {
    signal_id: string
    relevant_code_paths?: string[]
    verified?: boolean
}

export interface DismissalContent {
    reason?: string
    note?: string
}

export interface RepoSelectionContent {
    repository?: string | null
    reason?: string
}

export interface RelatedToContent {
    report_id?: string
}

export interface ReportLinkContent {
    kind?: string
    report_id?: string
    reason?: string | null
}

export interface AutostartSkipContent {
    skip_reason?: string
    linked_report_id?: string | null
    detail?: string
}

/** Short label for why automatic work was held back, shown next to the reason. */
export const AUTOSTART_SKIP_REASON_LABELS: Record<string, string> = {
    duplicate_of: 'Duplicate',
    blocked_by_dependency: 'Waiting on a dependency',
    plan_parent: 'Tracked by other reports',
}

export const REPORT_LINK_KIND_LABELS: Record<string, string> = {
    depends_on: 'Depends on',
    part_of: 'Part of',
    follow_up_of: 'Follow-up of',
    duplicate_of: 'Duplicate of',
    recurrence_of: 'Recurrence of',
}

export interface CodeReviewContent {
    repository?: string
    head_sha?: string
    head_branch?: string
    outcome?: 'published' | 'stored' | 'failed'
    pr_url?: string | null
    review_url?: string | null
    counts?: {
        must_fix?: number
        should_fix?: number
        consider?: number
    }
}

export interface CheckResultContent {
    check_id?: string
    kind?: string
    title?: string
    outcome?: 'passed' | 'failed' | 'errored' | 'inconclusive'
    explanation?: string
    observed_value?: number | null
    baseline_value?: number | null
    threshold?: string | null
    run_id?: string | null
}

/** What every entry in a check's life carries. Mirrors `CheckLifecycleEntry` in `artefact_schemas.py`. */
export interface CheckLifecycleContent {
    check_id?: string
    kind?: string
    title?: string
}

export interface CheckScheduledContent extends CheckLifecycleContent {
    rationale?: string
    next_run_at?: string
    arms_on_resolve?: boolean
    soak_minutes?: number | null
    skill_name?: string | null
    runs?: number
}

export interface CheckExpiredContent extends CheckLifecycleContent {
    expired_at?: string
    last_run_at?: string | null
}

export interface CheckCancelledContent extends CheckLifecycleContent {
    reason?: 'stopped_by_person' | 'stopped_by_scout' | 'replaced_by_research' | 'replaced_by_request'
}

export interface TitleChangeContent {
    old_title?: string | null
    new_title: string
}

export interface SummaryChangeContent {
    old_summary?: string | null
    new_summary: string
}

export interface ImplementationDecisionContent {
    supersede?: boolean
    blocked_reason?: 'revision_limit' | null
    reason?: string
    targets?: { pr_url: string }[]
}

export interface ImplementationReplacementContent {
    decision: ImplementationDecisionContent
}

export interface ImplementationHandoverContent {
    status: 'processing' | 'completed' | 'failed' | 'cancelled' | 'needs_attention'
    explanation?: string
    replacement_pr_urls?: string[]
    results?: Record<string, 'closed' | 'already_closed' | 'skipped'>
}

export interface WorkClaimContent {
    display_name?: string | null
}

export interface WorkReleaseContent {
    reason?: 'released' | 'taken_over'
}

export const WORK_RELEASE_REASON_LABELS: Record<NonNullable<WorkReleaseContent['reason']>, string> = {
    released: 'Released',
    taken_over: 'Taken over',
}

// ── Ranking scores (staff only) ──────────────────────────────────────────────────────────────

/**
 * One outcome head of a ranking model. `readable` is false when the head has no holdout AUC yet.
 * `lift` is the probability over the head's base rate, or null when the model saved no base rate.
 */
export interface RankingHead {
    name: string
    probability: number
    lift: number | null
    readable: boolean
}

export interface RankingModel {
    key: string
    roles: string[]
    status: 'scored' | 'skipped'
    skipReason: string | null
    /** Highest lift first. Heads without a lift come last, highest probability first. */
    heads: RankingHead[]
}

export interface RankingScoreView {
    scoredAt: string
    manifestVersion: string
    served: RankingModel
    challengers: RankingModel[]
}

/** Mirrors `readable_head_names` in `ranking/model_contract.py`. */
function readableHeadNames(metadata: unknown): Set<string> {
    const heads = isObject(metadata) && Array.isArray(metadata.heads) ? metadata.heads : []
    return new Set(
        heads.filter((entry) => isObject(entry) && entry.readable === true).map((entry) => String(entry.head))
    )
}

/** Mirrors `classification_thresholds` in `ranking/model_contract.py`. */
function classificationThresholds(metadata: unknown): Map<string, number> {
    const heads = isObject(metadata) && Array.isArray(metadata.heads) ? metadata.heads : []
    const thresholds = new Map<string, number>()
    for (const entry of heads) {
        if (isObject(entry) && typeof entry.refit_classification_threshold === 'number') {
            thresholds.set(String(entry.head), entry.refit_classification_threshold)
        }
    }
    return thresholds
}

/** Reads the stored lift first. Otherwise mirrors `head_lifts` in `ranking/model_contract.py`. */
function headLift(name: string, probability: number, lifts: unknown, thresholds: Map<string, number>): number | null {
    const stored = isObject(lifts) ? lifts[name] : undefined
    if (typeof stored === 'number' && Number.isFinite(stored)) {
        return stored
    }
    const threshold = thresholds.get(name) ?? 0
    return threshold > 0 ? probability / threshold : null
}

function compareRankingHeads(a: RankingHead, b: RankingHead): number {
    if (a.lift !== null && b.lift !== null) {
        return b.lift - a.lift
    }
    if (a.lift !== null || b.lift !== null) {
        return a.lift === null ? 1 : -1
    }
    return b.probability - a.probability
}

function readRankingModel(key: string, value: unknown): RankingModel | null {
    if (!isObject(value) || (value.status !== 'scored' && value.status !== 'skipped')) {
        return null
    }
    const readable = readableHeadNames(value.metadata)
    const thresholds = classificationThresholds(value.metadata)
    const heads = Object.entries(isObject(value.scores) ? value.scores : {})
        .filter((entry): entry is [string, number] => typeof entry[1] === 'number' && Number.isFinite(entry[1]))
        .map(([name, probability]) => ({
            name,
            probability,
            lift: headLift(name, probability, value.lifts, thresholds),
            readable: readable.has(name),
        }))
        .sort(compareRankingHeads)
    return {
        key,
        roles: Array.isArray(value.roles) ? value.roles.filter((role): role is string => typeof role === 'string') : [],
        status: value.status,
        skipReason: typeof value.skip_reason === 'string' ? value.skip_reason : null,
        heads,
    }
}

/**
 * Reads a `ranking_score` artefact (`RankingScore` in `artefact_schemas.py`). Returns null when the
 * content does not parse or the served model is missing, so the row shows only its label.
 */
export function readRankingScore(content: unknown): RankingScoreView | null {
    if (!isObject(content) || !isObject(content.results) || typeof content.served_key !== 'string') {
        return null
    }
    const models = Object.entries(content.results).map(([key, value]) => readRankingModel(key, value))
    const served = models.find((model) => model?.key === content.served_key)
    if (!served) {
        return null
    }
    return {
        scoredAt: typeof content.scored_at === 'string' ? content.scored_at : '',
        manifestVersion: typeof content.manifest_version === 'string' ? content.manifest_version : '',
        served,
        challengers: models.filter((model): model is RankingModel => !!model && model.key !== served.key),
    }
}

// ── Activity visibility ──────────────────────────────────────────────────────────────────────

/**
 * The activity rows worth showing a reader. A handover row lands once per attempt, so `processing`
 * rows are internal retry bookkeeping rather than something that happened to the report. The
 * activity count and the log itself both read this, so the two cannot disagree.
 */
export function selectVisibleReportActivity(artefacts: SignalReportArtefact[]): SignalReportArtefact[] {
    return artefacts.filter(
        (artefact) =>
            artefact.type !== 'implementation_dispatch' &&
            artefact.type !== 'impact_measurement_plan' &&
            (artefact.type !== 'implementation_handover' ||
                (artefact.content as ImplementationHandoverContent).status !== 'processing')
    )
}

// ── Type labels ──────────────────────────────────────────────────────────────────────────────

/** Human label for each artefact type as it reads in the activity log header. */
export const ARTEFACT_TYPE_LABELS: Record<string, string> = {
    code_reference: 'Code referenced',
    line_reference: 'Line highlighted',
    commit: 'Commit pushed',
    task_run: 'Task run',
    note: 'Note added',
    priority_judgment: 'Priority assessed',
    actionability_judgment: 'Actionability assessed',
    safety_judgment: 'Safety assessed',
    signal_finding: 'Signal investigated',
    suggested_reviewers: 'Reviewers suggested',
    repo_selection: 'Repo selected',
    dismissal: 'Report dismissed',
    video_segment: 'Video segment',
    title_change: 'Title edited',
    summary_change: 'Summary edited',
    related_to: 'Related report',
    report_link: 'Report linked',
    autostart_skip: 'Work not started',
    code_review: 'Code review',
    check_result: 'Follow-up check',
    check_scheduled: 'Follow-up check scheduled',
    check_expired: 'Follow-up check expired',
    check_cancelled: 'Follow-up check cancelled',
    implementation_decision: 'Open PR assessed',
    implementation_replacement: 'Replacement started',
    implementation_handover: 'Replacement outcome',
    ranking_score: 'Ranking scored',
    work_claim: 'Work claimed',
    work_release: 'Work released',
}

export function artefactTypeLabel(type: string): string {
    return ARTEFACT_TYPE_LABELS[type] ?? type
}

/**
 * The mono `file:line` location string shown next to the type label, or null when the artefact
 * type carries no location.
 */
export function artefactLocationLabel(artefact: SignalReportArtefact): string | null {
    if (artefact.type === 'code_reference') {
        const c = artefact.content as CodeReferenceContent
        if (!c?.file_path) {
            return null
        }
        if (c.start_line && c.end_line && c.start_line !== c.end_line) {
            return `${c.file_path}:${c.start_line}-${c.end_line}`
        }
        return c.start_line ? `${c.file_path}:${c.start_line}` : c.file_path
    }
    if (artefact.type === 'line_reference') {
        const c = artefact.content as LineReferenceContent
        if (!c?.file_path) {
            return null
        }
        return c.line ? `${c.file_path}:${c.line}` : c.file_path
    }
    return null
}

/** The human responsible for an activity, when there is one. */
export function artefactAttributionLabel(artefact: SignalReportArtefact): string | null {
    if (artefact.created_by) {
        return artefact.created_by.first_name?.trim() || artefact.created_by.email
    }
    return null
}

// ── Task-run purpose derivation (replaces the legacy SignalReportTask `relationship`) ──────────

/** A task↔report association's derived purpose. `other` covers custom-agent runs. */
export type ReportTaskPurpose = 'research' | 'implementation' | 'other'

/** Sort order for linked-task rows: implementation first, then research, then everything else. */
export const PURPOSE_ORDER: ReportTaskPurpose[] = ['implementation', 'research', 'other']

export interface DerivedPurpose {
    purpose: ReportTaskPurpose
    purposeLabel: string
}

/**
 * Derive a task's purpose + display label from its `task_run` artefact's `(product, type)` pair.
 * Returns null for `repo_selection` (pipeline plumbing, never displayed). The built-in signals
 * pipeline maps research/implementation to typed purposes; any other pair is `other`, labelled
 * from the humanized product + type. Mirrors the desktop `derivePurpose`.
 */
export function deriveTaskPurpose(content: TaskRunArtefactContent): DerivedPurpose | null {
    if (content.product === SIGNALS_PRODUCT) {
        if (content.type === 'research') {
            return { purpose: 'research', purposeLabel: 'Research' }
        }
        if (content.type === 'implementation') {
            return { purpose: 'implementation', purposeLabel: 'Implementation' }
        }
        if (content.type === 'repo_selection') {
            return null
        }
        if (content.type === 'scout') {
            return { purpose: 'other', purposeLabel: 'Scout' }
        }
        return { purpose: 'other', purposeLabel: `Signals: ${identifierToHuman(content.type)}` }
    }
    return {
        purpose: 'other',
        purposeLabel: `${identifierToHuman(content.product)}: ${identifierToHuman(content.type)}`,
    }
}

/**
 * Short type label for a `task_run` artefact's badge in the activity log. Unlike `deriveTaskPurpose`
 * this never returns null — `repo_selection` is shown here ("Repo selection") because the activity
 * log is the full work-log, whereas the Runs list hides selection plumbing.
 */
export function taskRunTypeLabel(content: TaskRunArtefactContent): string {
    if (content.product === SIGNALS_PRODUCT) {
        const labels: Record<string, string> = {
            research: 'Research',
            implementation: 'Implementation',
            repo_selection: 'Repo selection',
            scout: 'Scout',
        }
        return labels[content.type] ?? identifierToHuman(content.type)
    }
    return identifierToHuman(content.type)
}

/** Whether a `task_run` artefact came from a custom agent (non-signals product). */
export function isCustomAgentTaskRun(content: TaskRunArtefactContent): boolean {
    return content.product !== SIGNALS_PRODUCT
}
