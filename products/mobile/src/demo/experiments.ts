import { create } from 'zustand'

import type {
    EndExperimentBody,
    ExperimentApi,
    ExperimentExposureResponseApi,
    ExperimentFlagCleanupTargetApi,
    ExperimentHealthApi,
    ExperimentListSegment,
    ExperimentMetricResultRowApi,
    ExperimentPatch,
    ExperimentQueryResultApi,
    ExperimentRecalculationJobApi,
    ExperimentResultsRunApi,
    ExperimentRunningTimeTargetApi,
    ExperimentsListInput,
    ExperimentsPage,
    ExperimentsSource,
    RecalculationStart,
    ShipResult,
    ShipVariantBody,
} from '@/api/experiments'
import { EXPERIMENTS_PAGE_SIZE, SEGMENT_STATUSES } from '@/api/experiments'
import { sleep } from '@/lib/sleep'

import { useDemoMode } from './demoMode'
import { DEMO_ME } from './fixtures'
import { DEMO_READ_MS } from './views'

// Experiments demo data. Every name, number, email and repository is invented. Payloads have the API shapes, so demo
// mode runs through the same model, sort and copy as live mode. Writes change the store below, so a demo ship or end
// shows on the detail and moves the row to Done. Ids are stable because the Argent flow selects by them.

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR
/** The demo's daily run finished at this hour, local time. */
const DAILY_RUN_HOUR = 2
/** The server refuses a manual run this soon after the previous one. */
const MANUAL_WINDOW_MS = 5 * MINUTE
/** A demo recalculation finishes one metric per step. */
const RECALC_STEP_MS = 2_000

export const DEMO_EXPERIMENT_CHECKOUT = 101
export const DEMO_EXPERIMENT_PRICING = 102
export const DEMO_EXPERIMENT_FOLDERS = 103
export const DEMO_EXPERIMENT_ONBOARDING = 104
export const DEMO_EXPERIMENT_INVITE = 105
export const DEMO_EXPERIMENT_ANNUAL = 106
export const DEMO_EXPERIMENT_SIDEBAR = 107
export const DEMO_EXPERIMENT_REFERRAL = 108

const SAM = { id: 9101, uuid: 'demo-user-sam', first_name: 'Sam', last_name: 'Okafor', email: 'sam@example.com' }
const PRIYA = {
    id: 9102,
    uuid: 'demo-user-priya',
    first_name: 'Priya',
    last_name: 'Natarajan',
    email: 'priya@example.com',
}
const [ME_FIRST = 'You', ...ME_REST] = DEMO_ME.name.split(' ')
const ME = { id: 9100, uuid: DEMO_ME.uuid, first_name: ME_FIRST, last_name: ME_REST.join(' '), email: DEMO_ME.email }

type Person = typeof SAM
type Method = 'bayesian' | 'frequentist'

interface MetricDef {
    uuid: string
    name: string
    goal: 'increase' | 'decrease'
    type: 'funnel' | 'mean'
    event: string
}

/** One variant's numbers. `interval` is the relative change as fractions; control has none. */
interface StatDef {
    key: string
    n: number
    /** Conversions for a funnel, the total for a mean. */
    sum: number
    interval?: [number, number]
    chance?: number
    p?: number
    significant?: boolean
}

interface MetricResultDef {
    metric: MetricDef
    stats: StatDef[]
}

interface ExperimentDef {
    id: number
    name: string
    description: string
    flagKey: string
    creator: Person
    method: Method
    variants: { key: string; split: number }[]
    createdAgoMs: number
    /** Launch time before the anchor. Missing for a draft. */
    startedAgoMs?: number
    endedAgoMs?: number
    conclusion?: ExperimentApi['conclusion']
    conclusionComment?: string
    shipped?: string
    primary: MetricResultDef[]
    secondary: MetricResultDef[]
    target: { mde: number; recommended: number }
    exposures: number[]
    health: { code: string; severity: 'warning' | 'info'; title: string; detail: string }[]
    srmPValue?: number
    /** Every release group carries the freeze stamp, so the server reports `exposure_frozen`. */
    frozen?: boolean
}

function metric(
    uuid: string,
    name: string,
    event: string,
    type: MetricDef['type'] = 'funnel',
    goal: MetricDef['goal'] = 'increase'
): MetricDef {
    return { uuid, name, goal, type, event }
}

const DEFS: ExperimentDef[] = [
    {
        id: DEMO_EXPERIMENT_CHECKOUT,
        name: 'Checkout CTA copy',
        description:
            'If the checkout button says what happens next, like "Start trial", more people will finish checkout. The current "Continue" label does not say that nobody pays today.',
        flagKey: 'checkout-cta-copy',
        creator: SAM,
        method: 'bayesian',
        variants: [
            { key: 'control', split: 33 },
            { key: 'start-trial', split: 33 },
            { key: 'get-started', split: 34 },
        ],
        createdAgoMs: 14 * DAY,
        startedAgoMs: 12 * DAY + 3 * HOUR,
        primary: [
            {
                metric: metric('demo-m-checkout', 'Checkout completed', 'checkout_completed'),
                stats: [
                    { key: 'control', n: 2281, sum: 285 },
                    {
                        key: 'start-trial',
                        n: 2265,
                        sum: 318,
                        interval: [0.03, 0.218],
                        chance: 0.991,
                        significant: true,
                    },
                    { key: 'get-started', n: 2254, sum: 290, interval: [-0.059, 0.119], chance: 0.752 },
                ],
            },
        ],
        secondary: [
            {
                metric: metric('demo-m-revenue', 'Revenue per user', 'subscription_paid', 'mean'),
                stats: [
                    { key: 'control', n: 2281, sum: 9398 },
                    { key: 'start-trial', n: 2265, sum: 9762, interval: [-0.032, 0.124], chance: 0.874 },
                    { key: 'get-started', n: 2254, sum: 9219, interval: [-0.086, 0.072], chance: 0.431 },
                ],
            },
            {
                metric: metric(
                    'demo-m-tickets',
                    'Support tickets opened',
                    'support_ticket_opened',
                    'funnel',
                    'decrease'
                ),
                stats: [
                    { key: 'control', n: 2281, sum: 44 },
                    { key: 'start-trial', n: 2265, sum: 41, interval: [-0.381, 0.257], chance: 0.36 },
                    { key: 'get-started', n: 2254, sum: 46, interval: [-0.27, 0.386], chance: 0.625 },
                ],
            },
        ],
        target: { mde: 10, recommended: 6000 },
        exposures: [2281, 2265, 2254],
        health: [
            {
                code: 'multiple_variants_share',
                severity: 'info',
                title: '38 people saw more than one variant',
                detail: 'They are left out of the results. That is 0.6% of exposures.',
            },
        ],
    },
    {
        id: DEMO_EXPERIMENT_PRICING,
        name: 'Pricing page layout',
        description:
            'A side-by-side plan comparison will help people choose a plan faster, so more of them will start an upgrade from the pricing page.',
        flagKey: 'pricing-page-layout',
        creator: PRIYA,
        method: 'frequentist',
        variants: [
            { key: 'control', split: 50 },
            { key: 'comparison', split: 50 },
        ],
        createdAgoMs: 23 * DAY,
        startedAgoMs: 21 * DAY + 5 * HOUR,
        primary: [
            {
                metric: metric('demo-m-upgrade', 'Upgrade started', 'upgrade_started'),
                stats: [
                    { key: 'control', n: 9786, sum: 412 },
                    { key: 'comparison', n: 9724, sum: 352, interval: [-0.248, -0.032], p: 0.009, significant: true },
                ],
            },
        ],
        secondary: [
            {
                metric: metric('demo-m-compare', 'Plan comparison opened', 'plan_comparison_opened'),
                stats: [
                    { key: 'control', n: 9786, sum: 1801 },
                    { key: 'comparison', n: 9724, sum: 2208, interval: [0.189, 0.279], p: 0.0004, significant: true },
                ],
            },
        ],
        target: { mde: 8, recommended: 18000 },
        exposures: [9786, 9724],
        health: [],
    },
    {
        id: DEMO_EXPERIMENT_FOLDERS,
        name: 'Smart folder suggestions',
        description:
            'Suggesting a folder from the names of uploaded files will make it easier to get organized, so more people will create their first folder.',
        flagKey: 'smart-folder-suggestions',
        creator: ME,
        method: 'bayesian',
        variants: [
            { key: 'control', split: 50 },
            { key: 'suggestions', split: 50 },
        ],
        createdAgoMs: 3 * DAY,
        startedAgoMs: 38 * MINUTE,
        primary: [{ metric: metric('demo-m-folder', 'Folder created', 'folder_created'), stats: [] }],
        secondary: [],
        target: { mde: 10, recommended: 3000 },
        exposures: [109, 105],
        health: [],
    },
    {
        id: DEMO_EXPERIMENT_ONBOARDING,
        name: 'Onboarding checklist v2',
        description:
            'A shorter checklist that starts with uploading files will get more new teams to upload 3 files in their first week. That is our activation step.',
        flagKey: 'onboarding-checklist-v2',
        creator: SAM,
        method: 'bayesian',
        variants: [
            { key: 'control', split: 50 },
            { key: 'checklist-v2', split: 50 },
        ],
        createdAgoMs: 8 * DAY,
        startedAgoMs: 6 * DAY + 2 * HOUR,
        primary: [
            {
                metric: metric('demo-m-activation', 'Activation (3 files uploaded)', 'third_file_uploaded'),
                stats: [
                    { key: 'control', n: 1368, sum: 435 },
                    { key: 'checklist-v2', n: 1166, sum: 398, interval: [-0.02, 0.166], chance: 0.934 },
                ],
            },
        ],
        secondary: [
            {
                metric: metric('demo-m-day1', 'Files uploaded on day 1', 'file_uploaded', 'mean'),
                stats: [
                    { key: 'control', n: 1368, sum: 3283 },
                    { key: 'checklist-v2', n: 1166, sum: 3148, interval: [-0.018, 0.268], chance: 0.941 },
                ],
            },
        ],
        target: { mde: 12, recommended: 4200 },
        exposures: [1368, 1166],
        health: [
            {
                code: 'release_conditions_changed_mid_run',
                severity: 'warning',
                title: 'Release conditions changed while running',
                detail: 'They were edited two days after launch. This can cause an uneven split.',
            },
        ],
        srmPValue: 0.0004,
        frozen: true,
    },
    {
        id: DEMO_EXPERIMENT_INVITE,
        name: 'Invite reminder email',
        description:
            'Many invites sit unread in busy inboxes. A reminder 48 hours after the invite will get more invited people to accept and join their team.',
        flagKey: 'invite-reminder-email',
        creator: PRIYA,
        method: 'bayesian',
        variants: [
            { key: 'control', split: 50 },
            { key: 'reminder-48h', split: 50 },
        ],
        createdAgoMs: 5 * DAY,
        startedAgoMs: 4 * DAY + 1 * HOUR,
        primary: [
            {
                metric: metric('demo-m-invite', 'Invite accepted', 'invite_accepted'),
                stats: [
                    { key: 'control', n: 620, sum: 137 },
                    { key: 'reminder-48h', n: 622, sum: 143, interval: [-0.135, 0.215], chance: 0.648 },
                ],
            },
        ],
        secondary: [],
        target: { mde: 15, recommended: 2200 },
        exposures: [620, 622],
        health: [],
    },
    {
        id: DEMO_EXPERIMENT_ANNUAL,
        name: 'Annual plan toggle default',
        description:
            'If annual billing is selected by default, more free users will buy the annual plan, and the share who complete checkout will not drop.',
        flagKey: 'annual-plan-toggle',
        creator: ME,
        method: 'bayesian',
        variants: [
            { key: 'control', split: 50 },
            { key: 'annual-default', split: 50 },
        ],
        createdAgoMs: 2 * DAY + 4 * HOUR,
        primary: [{ metric: metric('demo-m-annual', 'Annual plan purchased', 'annual_plan_purchased'), stats: [] }],
        secondary: [
            { metric: metric('demo-m-annual-checkout', 'Checkout completed', 'checkout_completed'), stats: [] },
        ],
        target: { mde: 10, recommended: 2600 },
        exposures: [0, 0],
        health: [],
    },
    {
        id: DEMO_EXPERIMENT_SIDEBAR,
        name: 'Folder sidebar redesign',
        description:
            'A compact sidebar shows more folders without scrolling. People will find their files faster and open more folders per session.',
        flagKey: 'folder-sidebar-redesign',
        creator: SAM,
        method: 'bayesian',
        variants: [
            { key: 'control', split: 50 },
            { key: 'compact-sidebar', split: 50 },
        ],
        createdAgoMs: 27 * DAY,
        startedAgoMs: 25 * DAY,
        endedAgoMs: 7 * DAY,
        conclusion: 'won',
        conclusionComment:
            'Shipping the compact sidebar to everyone. More folders opened per session, and support tickets stayed flat.',
        shipped: 'compact-sidebar',
        primary: [
            {
                metric: metric('demo-m-folders-opened', 'Folders opened per session', 'folder_opened', 'mean'),
                stats: [
                    { key: 'control', n: 7140, sum: 24419 },
                    {
                        key: 'compact-sidebar',
                        n: 7066,
                        sum: 26356,
                        interval: [0.052, 0.13],
                        chance: 0.9995,
                        significant: true,
                    },
                ],
            },
        ],
        secondary: [],
        target: { mde: 5, recommended: 12000 },
        exposures: [7140, 7066],
        health: [],
    },
    {
        id: DEMO_EXPERIMENT_REFERRAL,
        name: 'Referral banner placement',
        description:
            'Moving the referral banner closer to where people share files will remind them at the right moment, so more of them will copy their referral link.',
        flagKey: 'referral-banner-placement',
        creator: PRIYA,
        method: 'bayesian',
        variants: [
            { key: 'control', split: 33 },
            { key: 'footer-banner', split: 33 },
            { key: 'inline-banner', split: 34 },
        ],
        createdAgoMs: 46 * DAY,
        startedAgoMs: 44 * DAY,
        endedAgoMs: 16 * DAY,
        conclusion: 'inconclusive',
        conclusionComment: 'No clear winner after four weeks. Keeping the current banner.',
        primary: [
            {
                metric: metric('demo-m-referral', 'Referral link copied', 'referral_link_copied'),
                stats: [
                    { key: 'control', n: 7652, sum: 116 },
                    { key: 'footer-banner', n: 7618, sum: 120, interval: [-0.098, 0.176], chance: 0.71 },
                    { key: 'inline-banner', n: 7640, sum: 114, interval: [-0.147, 0.115], chance: 0.402 },
                ],
            },
        ],
        secondary: [],
        target: { mde: 10, recommended: 21000 },
        exposures: [7652, 7618, 7640],
        health: [],
    },
]

const DEFS_BY_ID = new Map(DEFS.map((def) => [def.id, def]))

function iso(ms: number): string {
    return new Date(ms).toISOString()
}

/** The daily run's data cutoff: 02:00 local today, or yesterday when that is still ahead. */
export function demoDailyRunAt(anchor: number): number {
    const run = new Date(anchor)
    run.setHours(DAILY_RUN_HOUR, 0, 0, 0)
    if (run.getTime() > anchor) {
        run.setDate(run.getDate() - 1)
    }
    return run.getTime()
}

function metricJson(def: MetricDef): Record<string, unknown> {
    const source = { kind: 'EventsNode', event: def.event, name: def.event }
    return {
        kind: 'ExperimentMetric',
        uuid: def.uuid,
        name: def.name,
        goal: def.goal,
        metric_type: def.type,
        ...(def.type === 'funnel' ? { series: [source] } : { source }),
    }
}

function flagJson(def: ExperimentDef, active: boolean, shipped: string | null): Record<string, unknown> {
    return {
        id: def.id + 4000,
        team_id: 1,
        key: def.flagKey,
        name: `Feature flag for experiment ${def.name}`,
        active,
        deleted: false,
        ensure_experience_continuity: false,
        filters: {
            groups: [{ properties: [], rollout_percentage: 100, ...(def.frozen ? { exposure_frozen: true } : {}) }],
            multivariate: {
                variants: def.variants.map((variant) => ({
                    key: variant.key,
                    rollout_percentage: shipped ? (variant.key === shipped ? 100 : 0) : variant.split,
                })),
            },
        },
        evaluation_contexts: [],
    }
}

function experimentJson(def: ExperimentDef, anchor: number): ExperimentApi {
    const started = def.startedAgoMs === undefined ? null : anchor - def.startedAgoMs
    const ended = def.endedAgoMs === undefined ? null : anchor - def.endedAgoMs
    const status = started === null ? 'draft' : ended !== null ? 'stopped' : def.frozen ? 'exposure_frozen' : 'running'
    const json: Record<string, unknown> = {
        id: def.id,
        name: def.name,
        description: def.description,
        start_date: started === null ? null : iso(started),
        end_date: ended === null ? null : iso(ended),
        feature_flag_key: def.flagKey,
        feature_flag: flagJson(def, started !== null, def.shipped ?? null),
        feature_flag_rule_id: null,
        holdout: null,
        exposure_cohort: null,
        parameters: {},
        running_time_calculation: {
            minimum_detectable_effect: def.target.mde,
            recommended_sample_size: def.target.recommended,
        },
        excluded_variants: [],
        secondary_metrics: [],
        saved_metrics: [],
        filters: {},
        archived: false,
        deleted: false,
        created_by: { ...def.creator, distinct_id: def.creator.uuid, is_email_verified: true, hedgehog_config: null },
        created_at: iso(anchor - def.createdAgoMs),
        updated_at: iso(ended ?? started ?? anchor - def.createdAgoMs),
        type: 'product',
        exposure_criteria: { filterTestAccounts: true },
        metrics: def.primary.map((result) => metricJson(result.metric)),
        metrics_secondary: def.secondary.map((result) => metricJson(result.metric)),
        stats_config: { method: def.method },
        conclusion: def.conclusion ?? null,
        conclusion_comment: def.conclusionComment ?? null,
        flag_cleanup_task_id: null,
        repository: null,
        primary_metrics_ordered_uuids: null,
        secondary_metrics_ordered_uuids: null,
        version: 1,
        status,
        is_legacy: false,
        can_freeze_exposure: status === 'running',
        resolved_exposure_event: '$feature_flag_called',
        health: null,
        user_access_level: 'editor',
        tags: [],
    }
    return json as unknown as ExperimentApi
}

function resultJson(def: ExperimentDef, result: MetricResultDef): ExperimentQueryResultApi | null {
    const [control, ...variants] = result.stats
    if (!control || !variants.length) {
        return null
    }
    const squares = (stat: StatDef): number =>
        result.metric.type === 'funnel' ? stat.sum : (stat.sum * stat.sum) / Math.max(1, stat.n) + stat.n
    return {
        kind: 'ExperimentQuery',
        baseline: { key: control.key, number_of_samples: control.n, sum: control.sum, sum_squares: squares(control) },
        variant_results: variants.map((stat) => ({
            key: stat.key,
            number_of_samples: stat.n,
            sum: stat.sum,
            sum_squares: squares(stat),
            method: def.method,
            significant: stat.significant ?? false,
            ...(def.method === 'bayesian'
                ? { chance_to_win: stat.chance ?? 0.5, credible_interval: stat.interval ?? [0, 0] }
                : { p_value: stat.p ?? 1, confidence_interval: stat.interval ?? [0, 0] }),
        })),
    }
}

function resultRows(def: ExperimentDef): ExperimentMetricResultRowApi[] {
    return [...def.primary, ...def.secondary].flatMap((result): ExperimentMetricResultRowApi[] => {
        const json = resultJson(def, result)
        return json
            ? [
                  {
                      metric_uuid: result.metric.uuid,
                      status: 'completed',
                      result: json,
                      error_message: null,
                      configuration_status: 'current',
                  },
              ]
            : []
    })
}

interface DemoRun {
    id: string
    experimentId: string
    startedAt: number
    totalMetrics: number
}

interface DemoExperimentsState {
    anchor: number
    experiments: Record<string, ExperimentApi>
    /** When the stored results cover data up to, per experiment. Missing means no results yet. */
    resultsAt: Record<string, number>
    runs: Record<string, DemoRun>
    /** The run each experiment's latest results come from. */
    latestRunId: Record<string, string>
    lastManualAt: Record<string, number>
    runCounter: number
}

function freshDemoState(anchor: number): DemoExperimentsState {
    const daily = demoDailyRunAt(anchor)
    const experiments: Record<string, ExperimentApi> = {}
    const resultsAt: Record<string, number> = {}
    for (const def of DEFS) {
        experiments[String(def.id)] = experimentJson(def, anchor)
        if (resultRows(def).length) {
            // An ended experiment's results stop at its end date.
            resultsAt[String(def.id)] = def.endedAgoMs === undefined ? daily : anchor - def.endedAgoMs
        }
    }
    return { anchor, experiments, resultsAt, runs: {}, latestRunId: {}, lastManualAt: {}, runCounter: 0 }
}

/** Not persisted: the demo starts over with the app, the same as its other fixtures. */
export const useDemoExperiments = create<DemoExperimentsState>(() => freshDemoState(Date.now()))

function demoState(): DemoExperimentsState {
    const anchor = useDemoMode.getState().anchor
    if (useDemoExperiments.getState().anchor !== anchor) {
        useDemoExperiments.setState(freshDemoState(anchor), true)
    }
    return useDemoExperiments.getState()
}

export function resetDemoExperiments(): void {
    useDemoExperiments.setState(freshDemoState(useDemoMode.getState().anchor), true)
}

function notFound(): Error {
    return new Error("This experiment isn't in the demo. Go back to the list and pick another one.")
}

function demoExperiment(id: string | number): ExperimentApi {
    const experiment = demoState().experiments[String(id)]
    if (!experiment) {
        throw notFound()
    }
    return experiment
}

function writeExperiment(id: string | number, patch: (experiment: ExperimentApi) => ExperimentApi): ExperimentApi {
    const next = patch(demoExperiment(id))
    useDemoExperiments.setState((state) => ({ experiments: { ...state.experiments, [String(id)]: next } }))
    return next
}

function withFlag(experiment: ExperimentApi, flag: Record<string, unknown>): ExperimentApi {
    return { ...experiment, feature_flag: { ...experiment.feature_flag, ...flag } } as ExperimentApi
}

const SEGMENT_FILTER: Record<ExperimentListSegment, (experiment: ExperimentApi) => boolean> = {
    running: (experiment) => (SEGMENT_STATUSES.running as readonly string[]).includes(experiment.status),
    complete: (experiment) => experiment.status === 'stopped',
    draft: (experiment) => experiment.status === 'draft',
}

async function demoFetchExperiments(
    input: ExperimentsListInput,
    signal?: AbortSignal,
    offset = 0
): Promise<ExperimentsPage> {
    await sleep(DEMO_READ_MS, signal)
    const search = input.search?.trim().toLowerCase() ?? ''
    const matches = Object.values(demoState().experiments)
        .filter((experiment) => !experiment.archived && SEGMENT_FILTER[input.status](experiment))
        .filter(
            (experiment) =>
                !search ||
                experiment.name.toLowerCase().includes(search) ||
                experiment.feature_flag_key.toLowerCase().includes(search)
        )
    return {
        results: matches.slice(offset, offset + EXPERIMENTS_PAGE_SIZE),
        hasMore: matches.length > offset + EXPERIMENTS_PAGE_SIZE,
        nextOffset: offset + EXPERIMENTS_PAGE_SIZE,
    }
}

async function demoFetchExperiment(id: string | number, signal?: AbortSignal): Promise<ExperimentApi> {
    await sleep(DEMO_READ_MS, signal)
    return demoExperiment(id)
}

function runPayload(experimentId: string, run: DemoRun, now: number): ExperimentResultsRunApi {
    const def = DEFS_BY_ID.get(Number(experimentId))
    const done = Math.min(run.totalMetrics, Math.floor((now - run.startedAt) / RECALC_STEP_MS))
    const complete = isFinished(run, now)
    const finishedAt = run.startedAt + run.totalMetrics * RECALC_STEP_MS
    return {
        id: run.id,
        experiment_id: Number(experimentId),
        status: complete ? 'completed' : 'in_progress',
        total_metrics: run.totalMetrics,
        completed_metrics: done,
        failed_metrics: 0,
        metric_errors: {},
        metric_retries: {},
        created_at: iso(run.startedAt),
        started_at: iso(run.startedAt),
        completed_at: complete ? iso(finishedAt) : null,
        query_to: iso(run.startedAt),
        results: complete && def ? resultRows(def) : [],
        rows_read: null,
        estimated_rows_total: null,
    }
}

function runsOf(experimentId: string): DemoRun[] {
    return Object.values(demoState().runs).filter((run) => run.experimentId === experimentId)
}

function isFinished(run: DemoRun, now: number): boolean {
    return now - run.startedAt >= run.totalMetrics * RECALC_STEP_MS
}

/** Finishes a demo run once its time is up, so `latest` points at it from then on. */
function settleRuns(experimentId: string, now: number): void {
    const finished = runsOf(experimentId)
        .filter((run) => isFinished(run, now))
        .sort((a, b) => b.startedAt - a.startedAt)[0]
    if (!finished || demoState().latestRunId[experimentId] === finished.id) {
        return
    }
    useDemoExperiments.setState((current) => ({
        latestRunId: { ...current.latestRunId, [experimentId]: finished.id },
        resultsAt: { ...current.resultsAt, [experimentId]: finished.startedAt },
    }))
}

function activeRun(experimentId: string, now: number): DemoRun | null {
    return runsOf(experimentId).find((run) => !isFinished(run, now)) ?? null
}

async function demoFetchLatestResults(
    id: string | number,
    signal?: AbortSignal
): Promise<ExperimentResultsRunApi | null> {
    await sleep(DEMO_READ_MS, signal)
    const key = String(id)
    const now = Date.now()
    settleRuns(key, now)
    const state = demoState()
    const def = DEFS_BY_ID.get(Number(key))
    const at = state.resultsAt[key]
    if (!def || at === undefined || !resultRows(def).length) {
        return null
    }
    const active = activeRun(key, now)
    const rows = resultRows(def)
    return {
        id: state.latestRunId[key] ?? `00000000-0000-4000-8000-00000000${key.padStart(4, '0')}`,
        experiment_id: def.id,
        status: 'completed',
        total_metrics: rows.length,
        completed_metrics: rows.length,
        failed_metrics: 0,
        metric_errors: {},
        metric_retries: {},
        created_at: iso(at),
        started_at: iso(at),
        completed_at: iso(at + 4 * MINUTE),
        query_to: iso(at),
        results: rows,
        rows_read: null,
        estimated_rows_total: null,
        active_run: active ? { id: active.id, status: 'in_progress' } : null,
        result_source: state.latestRunId[key] ? 'recalculation' : 'timeseries_fallback',
        exceeds_recalculation_age_limit: false,
    }
}

async function demoFetchResultsRun(
    id: string | number,
    runId: string,
    signal?: AbortSignal
): Promise<ExperimentResultsRunApi> {
    await sleep(DEMO_READ_MS, signal)
    const run = demoState().runs[runId]
    if (!run) {
        throw new Error('This refresh is no longer available. Pull to refresh again.')
    }
    settleRuns(String(id), Date.now())
    return runPayload(String(id), run, Date.now())
}

async function demoStartRecalculation(id: string | number): Promise<RecalculationStart> {
    await sleep(DEMO_READ_MS)
    const key = String(id)
    const def = DEFS_BY_ID.get(Number(key))
    if (!def) {
        throw notFound()
    }
    const now = Date.now()
    const running = activeRun(key, now)
    const last = demoState().lastManualAt[key]
    if (!running && last !== undefined && now - last < MANUAL_WINDOW_MS) {
        return { run: null, retryAfterMs: MANUAL_WINDOW_MS - (now - last) }
    }
    const run: DemoRun = running ?? {
        id: `00000000-0000-4000-9000-${String(demoState().runCounter + 1).padStart(12, '0')}`,
        experimentId: key,
        startedAt: now,
        totalMetrics: Math.max(1, resultRows(def).length),
    }
    if (!running) {
        useDemoExperiments.setState((state) => ({
            runs: { ...state.runs, [run.id]: run },
            lastManualAt: { ...state.lastManualAt, [key]: now },
            runCounter: state.runCounter + 1,
        }))
    }
    const payload = runPayload(key, run, now)
    const job: ExperimentRecalculationJobApi = {
        id: payload.id,
        experiment_id: payload.experiment_id,
        status: running ? 'in_progress' : 'pending',
        total_metrics: payload.total_metrics,
        completed_metrics: payload.completed_metrics,
        failed_metrics: 0,
        metric_errors: {},
        created_at: payload.created_at,
        started_at: payload.started_at,
        completed_at: null,
        query_to: null,
        is_existing: running !== null,
    }
    return { run: job, retryAfterMs: null }
}

function totalExposures(def: ExperimentDef): number {
    return def.exposures.reduce((sum, count) => sum + count, 0)
}

async function demoFetchRunningTimeTarget(
    id: string | number,
    signal?: AbortSignal
): Promise<ExperimentRunningTimeTargetApi> {
    await sleep(DEMO_READ_MS, signal)
    const experiment = demoExperiment(id)
    const def = DEFS_BY_ID.get(Number(id))
    if (!def) {
        throw notFound()
    }
    const started = experiment.start_date ? Date.parse(experiment.start_date) : null
    const days = started === null ? 0 : (demoState().anchor - started) / DAY
    const current = started === null ? null : totalExposures(def)
    const perDay = current && days > 0 ? current / days : 0
    return {
        minimum_detectable_effect: def.target.mde,
        recommended_sample_size: def.target.recommended,
        current_sample_size: current,
        outlook:
            current === null || days < 0.1
                ? null
                : {
                      days_since_launch: days,
                      exposures_per_day: perDay,
                      detectable_effect_now: Math.max(1, def.target.mde * Math.sqrt(def.target.recommended / current)),
                      upcoming_checkpoints: [],
                      reachable_effect: Math.max(1, def.target.mde * 0.8),
                  },
    }
}

async function demoFetchHealth(id: string | number, signal?: AbortSignal): Promise<ExperimentHealthApi> {
    await sleep(DEMO_READ_MS, signal)
    const def = DEFS_BY_ID.get(Number(id))
    if (!def) {
        throw notFound()
    }
    const findings = def.health.map((finding) => ({
        code: finding.code,
        subcode: null,
        reason: null,
        severity: finding.severity,
        title: finding.title,
        detail: finding.detail,
        evidence: {},
        actions: [],
        diagnostic_ref: null,
        check: finding.code,
    }))
    return { findings, checks: [], setup: null } as unknown as ExperimentHealthApi
}

/** Exposures arrive over the experiment's days; a launch under a day old gets hourly-sized buckets. */
async function demoFetchExposures(
    experiment: ExperimentApi,
    signal?: AbortSignal,
    asOf?: string | null
): Promise<ExperimentExposureResponseApi> {
    await sleep(DEMO_READ_MS, signal)
    const def = DEFS_BY_ID.get(experiment.id)
    const started = experiment.start_date ? Date.parse(experiment.start_date) : null
    if (!def || started === null) {
        return { timeseries: [], total_exposures: {} }
    }
    const anchor = demoState().anchor
    const asOfMs = asOf ? Date.parse(asOf) : Number.NaN
    const end = Math.min(
        experiment.end_date ? Date.parse(experiment.end_date) : anchor,
        Number.isNaN(asOfMs) ? Number.POSITIVE_INFINITY : asOfMs
    )
    const days = Math.max(1, Math.ceil((end - started) / DAY))
    const launchedNow = def.startedAgoMs === undefined
    const total: Record<string, number> = {}
    const timeseries = def.variants.map((variant, index) => {
        const count = launchedNow ? 0 : (def.exposures[index] ?? 0)
        total[variant.key] = count
        let running = 0
        const exposure_counts = Array.from({ length: days }, (_, day) => {
            running = Math.round((count * (day + 1)) / days)
            return running
        })
        return {
            variant: variant.key,
            days: Array.from({ length: days }, (_, day) => iso(started + day * DAY).slice(0, 10)),
            exposure_counts,
        }
    })
    const observedTotal = Object.values(total).reduce((sum, count) => sum + count, 0)
    const totalWeight = def.variants.reduce((sum, variant) => sum + variant.split, 0)
    const expected = Object.fromEntries(
        def.variants.map((variant) => [variant.key, (variant.split / totalWeight) * observedTotal])
    )
    return {
        timeseries,
        total_exposures: total,
        sample_ratio_mismatch: def.srmPValue === undefined ? null : { expected, p_value: def.srmPValue },
        health_findings: [],
        date_range: { date_from: iso(started), date_to: iso(end) },
    }
}

async function demoFetchFlagCleanupTarget(
    _id: string | number,
    signal?: AbortSignal
): Promise<ExperimentFlagCleanupTargetApi> {
    await sleep(DEMO_READ_MS, signal)
    return { repository: 'example-org/web-app', source: 'single_repo', candidates: ['example-org/web-app'] }
}

async function demoWrite<T>(write: () => T): Promise<T> {
    await sleep(DEMO_READ_MS)
    return write()
}

function demoLaunchExperiment(id: string | number): Promise<ExperimentApi> {
    return demoWrite(() =>
        writeExperiment(id, (experiment) => {
            if (experiment.status !== 'draft') {
                throw new Error('This experiment has already been launched.')
            }
            return withFlag({ ...experiment, status: 'running', start_date: iso(Date.now()) }, { active: true })
        })
    )
}

/** The server opens a cleanup PR only with a conclusion, and answers the task id on the experiment. */
function endedPatch(experiment: ExperimentApi, body: EndExperimentBody): ExperimentApi {
    const cleanup = body.open_cleanup_pr === true && Boolean(body.conclusion)
    return {
        ...experiment,
        status: 'stopped',
        end_date: experiment.end_date ?? iso(Date.now()),
        conclusion: body.conclusion ?? null,
        conclusion_comment: body.conclusion_comment ?? null,
        flag_cleanup_task_id: cleanup
            ? `00000000-0000-4000-a000-${String(experiment.id).padStart(12, '0')}`
            : experiment.flag_cleanup_task_id,
    }
}

function demoEndExperiment(id: string | number, body: EndExperimentBody): Promise<ExperimentApi> {
    return demoWrite(() =>
        writeExperiment(id, (experiment) => {
            if (experiment.status === 'draft' || experiment.status === 'stopped') {
                throw new Error('Only a running experiment can end.')
            }
            return endedPatch(experiment, body)
        })
    )
}

function demoShipVariant(id: string | number, body: ShipVariantBody): Promise<ShipResult> {
    return demoWrite(() => {
        const experiment = writeExperiment(id, (current) => {
            const def = DEFS_BY_ID.get(current.id)
            if (current.status === 'draft' || !def?.variants.some((variant) => variant.key === body.variant_key)) {
                throw new Error('This variant cannot ship from the demo.')
            }
            const flag = flagJson(def, true, body.variant_key)
            const filters = flag.filters as { groups: Record<string, unknown>[] }
            if (body.release_to_everyone) {
                filters.groups = [{ properties: [], rollout_percentage: 100 }, ...filters.groups]
            }
            return withFlag(
                endedPatch(current, {
                    ...body,
                    conclusion: body.conclusion ?? current.conclusion,
                    conclusion_comment: body.conclusion_comment ?? current.conclusion_comment,
                }),
                flag
            )
        })
        return { status: 'shipped', experiment }
    })
}

function demoPauseExperiment(id: string | number): Promise<ExperimentApi> {
    return demoWrite(() =>
        writeExperiment(id, (experiment) => withFlag({ ...experiment, status: 'paused' }, { active: false }))
    )
}

function demoResumeExperiment(id: string | number): Promise<ExperimentApi> {
    return demoWrite(() =>
        writeExperiment(id, (experiment) =>
            withFlag(
                { ...experiment, status: DEFS_BY_ID.get(experiment.id)?.frozen ? 'exposure_frozen' : 'running' },
                { active: true }
            )
        )
    )
}

function demoArchiveExperiment(id: string | number): Promise<ExperimentApi> {
    return demoWrite(() =>
        writeExperiment(id, (experiment) => {
            if (experiment.status !== 'stopped') {
                throw new Error('End the experiment before you archive it.')
            }
            return { ...experiment, archived: true }
        })
    )
}

function demoUpdateExperiment(id: string | number, patch: ExperimentPatch): Promise<ExperimentApi> {
    return demoWrite(() => writeExperiment(id, (experiment) => ({ ...experiment, ...patch })))
}

export const demoExperimentsSource: ExperimentsSource = {
    fetchExperiments: demoFetchExperiments,
    fetchExperiment: demoFetchExperiment,
    fetchLatestResults: demoFetchLatestResults,
    fetchResultsRun: demoFetchResultsRun,
    startRecalculation: demoStartRecalculation,
    fetchRunningTimeTarget: demoFetchRunningTimeTarget,
    fetchHealth: demoFetchHealth,
    fetchExposures: demoFetchExposures,
    fetchFlagCleanupTarget: demoFetchFlagCleanupTarget,
    launchExperiment: demoLaunchExperiment,
    endExperiment: demoEndExperiment,
    shipVariant: demoShipVariant,
    pauseExperiment: demoPauseExperiment,
    resumeExperiment: demoResumeExperiment,
    archiveExperiment: demoArchiveExperiment,
    updateExperiment: demoUpdateExperiment,
}
