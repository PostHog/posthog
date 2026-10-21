import type { ExperimentWarning } from 'scenes/experiments/experimentLogic'

import type { ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'

import type {
    ExperimentHealthApi,
    ExperimentHealthFindingApi,
    ExperimentHealthInputsExposuresApi,
    HealthExposureInputsStatusEnumApi,
} from '../../generated/api.schemas'
import { FLAG_STATE_FINDING_CODES, experimentWarningFromHealth } from '../experimentHealthFindingEvents'
import type { HealthPanelFinding } from '../healthPanelFindings'

export type HealthDebugDomain = 'experiment' | 'flag' | 'exposures' | 'metrics' | 'project' | 'raw'

export const HEALTH_DEBUG_DOMAIN_LABELS: Record<HealthDebugDomain, string> = {
    experiment: 'Experiment',
    flag: 'Feature flag',
    exposures: 'Exposures',
    metrics: 'Metrics',
    project: 'Project',
    raw: 'Raw data',
}

export type HealthDebugSource = 'health endpoint' | 'exposure query'

export interface HealthDebugCheck {
    check: string
    source: HealthDebugSource
    /** The input domains the check reads, as the input tabs name them. */
    reads: HealthDebugDomain[]
    result: string
    /** The severity of the finding behind the result. Null when the check gave no finding. */
    severity: HealthPanelFinding['severity'] | null
    /** What the page gives for the same check: its older rules, or its own exposure answer. Null when it has none. */
    browser: string | null
    browserLabel: string
    /** When the server's answer and the page's were computed, for the exposure checks. Null otherwise. */
    computedAt: string | null
    browserComputedAt: string | null
    /** 'disagrees' when the page's rules and the server's check read the same state and differ. 'drift' when the
     * server's exposure answer and the page's differ, which is expected, because they are computed at other times. */
    difference: 'disagrees' | 'drift' | null
    /** The values behind the result, or why the check gave none. */
    note: string | null
}

export interface HealthDebugInput {
    health: ExperimentHealthApi | null
    browserWarning: ExperimentWarning | null
    browserNoMetricsWarning: boolean
    isExperimentDraft: boolean
    exposures: ExperimentExposureQueryResponse | null | undefined
    exposuresLoading: boolean
    /** The exposure answer that the server's exposure checks read. Null until the health inputs load. */
    serverExposures: ExperimentHealthInputsExposuresApi | null
    serverExposuresLoading: boolean
}

const NO_FINDING = 'no finding'
const NOT_LOADED = 'not loaded'
const BROWSER_RULES = 'Browser rules'
const NO_TIMES = { computedAt: null, browserComputedAt: null }

const SERVER_EXPOSURES_UNAVAILABLE: Record<Exclude<HealthExposureInputsStatusEnumApi, 'ready' | 'stale'>, string> = {
    calculating: 'calculating: no cached answer yet',
    not_launched: 'skipped: not launched',
    no_query_access: 'skipped: you may not query events',
    failed: 'failed: the exposure query failed',
}

export function describeServerHealth(health: ExperimentHealthApi | null): string {
    return health ? `${health.findings.length} findings` : `${NOT_LOADED}: the health request is pending or failed`
}

export function describePanel(panelFindings: HealthPanelFinding[] | null): string {
    if (panelFindings === null) {
        return 'hidden: no server health, so the page shows its separate warnings'
    }
    if (panelFindings.length === 0) {
        return 'hidden: no findings'
    }
    return `shows ${panelFindings.length} findings`
}

function warningLabel(warning: ExperimentWarning | null): string {
    if (!warning) {
        return NO_FINDING
    }
    return warning.variantKey ? `${warning.key} (${warning.variantKey})` : warning.key
}

interface CheckResult {
    result: string
    severity: HealthPanelFinding['severity'] | null
}

function describeFinding(check: string, finding: Pick<HealthPanelFinding, 'code' | 'subcode' | 'evidence'>): string {
    const variantKey = finding.evidence.variant_key
    const name = finding.code === check ? finding.subcode : [finding.code, finding.subcode].filter(Boolean).join(' · ')
    return [name || 'finding', typeof variantKey === 'string' ? `(${variantKey})` : null].filter(Boolean).join(' ')
}

function serverResult(
    check: string,
    health: ExperimentHealthApi | null,
    matches: (code: ExperimentHealthFindingApi['code']) => boolean
): CheckResult {
    if (!health) {
        return { result: NOT_LOADED, severity: null }
    }
    const finding = health.findings.find((candidate) => matches(candidate.code))
    return finding
        ? { result: describeFinding(check, finding), severity: finding.severity }
        : { result: NO_FINDING, severity: null }
}

function findingOf(
    input: HealthDebugInput,
    code: ExperimentHealthFindingApi['code']
): ExperimentHealthFindingApi | null {
    return input.health?.findings.find((finding) => finding.code === code) ?? null
}

function flagStateCheck(input: HealthDebugInput): HealthDebugCheck {
    const serverWarning = input.health ? experimentWarningFromHealth(input.health) : null
    // A subcode the page does not know maps to no warning, so it can match a browser that finds none.
    // The raw finding still counts as a difference then.
    const hasUnmappedServerFinding =
        !serverWarning && !!input.health?.findings.some((finding) => FLAG_STATE_FINDING_CODES.has(finding.code))
    const differs =
        !!input.health &&
        (hasUnmappedServerFinding || warningLabel(serverWarning) !== warningLabel(input.browserWarning))
    return {
        check: 'flag_state',
        source: 'health endpoint',
        reads: ['experiment', 'flag'],
        ...serverResult('flag_state', input.health, (code) => FLAG_STATE_FINDING_CODES.has(code)),
        browser: warningLabel(input.browserWarning),
        browserLabel: BROWSER_RULES,
        ...NO_TIMES,
        difference: differs ? 'disagrees' : null,
        note: differs ? "The page shows the server's finding." : null,
    }
}

function share(value: unknown): string | null {
    return typeof value === 'number' ? `${(value * 100).toFixed(1)}%` : null
}

function serverOnlyCheck(
    input: HealthDebugInput,
    check: ExperimentHealthFindingApi['code'],
    note: ((finding: ExperimentHealthFindingApi) => string) | null,
    reads: HealthDebugDomain[] = ['experiment', 'flag']
): HealthDebugCheck {
    const finding = findingOf(input, check)
    return {
        check,
        source: 'health endpoint',
        reads,
        ...serverResult(check, input.health, (code) => code === check),
        browser: null,
        browserLabel: BROWSER_RULES,
        ...NO_TIMES,
        difference: null,
        note: finding && note ? note(finding) : null,
    }
}

function exposedBeforeFirst({ evidence }: ExperimentHealthFindingApi): string {
    const exposedBefore = evidence.exposed_before_change
    return `Exposed before the first: ${exposedBefore == null ? 'unknown' : exposedBefore ? 'yes' : 'no'}.`
}

function splitChangedNote(finding: ExperimentHealthFindingApi): string {
    const { evidence } = finding
    if (finding.subcode === 'not_checked') {
        return evidence.change_count == null
            ? `Not checked: ${evidence.reason}.`
            : `Not checked: ${evidence.reason}. ${evidence.change_count} changes since launch, from ${evidence.from} to ${evidence.to}.`
    }
    return `${evidence.change_count} counted changes, from ${evidence.from} to ${evidence.to}. ${exposedBeforeFirst(finding)}`
}

function bucketingChangedNote(finding: ExperimentHealthFindingApi): string {
    const { evidence } = finding
    const changed = `${evidence.change_count} saves changed ${evidence.changed_settings}.`
    return finding.subcode === 'not_checked'
        ? `Not checked: ${evidence.reason}. ${changed}`
        : `${changed} ${exposedBeforeFirst(finding)}`
}

function conditionsChangedNote(finding: ExperimentHealthFindingApi): string {
    const { evidence } = finding
    const changed = `${evidence.change_count} changes, from ${evidence.conditions_before} to ${evidence.conditions_after} conditions.`
    if (finding.subcode === 'not_checked') {
        return `Not checked: ${evidence.reason}. ${changed}`
    }
    const pinnedShare = share(evidence.pinned_share)
    const removedOverride = pinnedShare
        ? `Removed override share ${pinnedShare}.`
        : typeof evidence.reason === 'string'
          ? `Removed override share unknown: ${evidence.reason}.`
          : null
    return [changed, exposedBeforeFirst(finding), removedOverride].filter(Boolean).join(' ')
}

function forcedVariantNote(finding: ExperimentHealthFindingApi): string {
    const { evidence } = finding
    const parts = [`Pinned sets: ${evidence.pinned_condition_sets}, to ${evidence.pinned_variant_keys}.`]
    if (typeof evidence.pinned_people === 'number') {
        parts.push(`${evidence.pinned_people} of ${evidence.matched_people} matched people pinned.`)
    }
    const pinnedShare = share(evidence.pinned_share)
    if (pinnedShare) {
        parts.push(`Pinned share ${pinnedShare}.`)
    }
    const remoteShare = share(evidence.remotely_evaluated_share)
    if (remoteShare) {
        parts.push(`${remoteShare} of calls evaluated by the flag service.`)
    }
    if (typeof evidence.reason === 'string') {
        parts.push(`Share unknown: ${evidence.reason}.`)
    }
    return parts.join(' ')
}

function metricEventNote({ evidence }: ExperimentHealthFindingApi): string {
    const events = Object.entries(evidence)
        .filter(([key]) => /^metric_\d+_events$/.test(key))
        .map(([, value]) => value)
    return `Not received: ${events.join(', ')}.`
}

function exposureCriteriaNote({ subcode, evidence }: ExperimentHealthFindingApi): string {
    return subcode === 'filter_on_another_flag'
        ? `The query requires ${evidence.flag_key}, a filter requires ${evidence.filter_flag_keys}.`
        : `Not received: ${evidence.event}.`
}

function noMetricCheck(input: HealthDebugInput): HealthDebugCheck {
    const serverFires = !!findingOf(input, 'no_metric')
    const differs = !!input.health && input.browserNoMetricsWarning !== serverFires
    return {
        check: 'no_metric',
        source: 'health endpoint',
        reads: ['metrics'],
        ...serverResult('no_metric', input.health, (code) => code === 'no_metric'),
        browser: input.browserNoMetricsWarning ? 'no_metric' : NO_FINDING,
        browserLabel: BROWSER_RULES,
        ...NO_TIMES,
        difference: differs ? 'disagrees' : null,
        note: differs ? "The page shows the server's finding." : null,
    }
}

function serverExposureResult(input: HealthDebugInput, code: HealthPanelFinding['code']): CheckResult {
    const exposures = input.serverExposures
    if (!exposures) {
        return { result: input.serverExposuresLoading ? 'loading' : NOT_LOADED, severity: null }
    }
    if (exposures.status !== 'ready' && exposures.status !== 'stale') {
        return { result: SERVER_EXPOSURES_UNAVAILABLE[exposures.status], severity: null }
    }
    const finding = exposures.findings.find((candidate) => candidate.code === code)
    return finding
        ? { result: describeFinding(code, finding), severity: finding.severity }
        : { result: NO_FINDING, severity: null }
}

function pageExposureResult(input: HealthDebugInput, code: HealthPanelFinding['code']): string | null {
    if (input.isExperimentDraft || !input.exposures) {
        return null
    }
    // Read from the page's own answer, which holds its findings even when the health panel is unavailable.
    const finding = input.exposures.health_findings?.find((candidate) => candidate.code === code)
    return finding ? describeFinding(code, finding) : NO_FINDING
}

// The page's answer comes from the cache, but its type does not declare the cache fields.
function pageComputedAt(exposures: HealthDebugInput['exposures']): string | null {
    return exposures && 'last_refresh' in exposures && typeof exposures.last_refresh === 'string'
        ? exposures.last_refresh
        : null
}

function exposureChecks(input: HealthDebugInput): HealthDebugCheck[] {
    const exposureCheck = (
        check: HealthPanelFinding['code'],
        reads: HealthDebugDomain[],
        note: string | null
    ): HealthDebugCheck => {
        const server = serverExposureResult(input, check)
        const page = pageExposureResult(input, check)
        const serverAnswered = input.serverExposures?.status === 'ready' || input.serverExposures?.status === 'stale'
        return {
            check,
            source: 'exposure query',
            reads,
            ...server,
            browser: page,
            browserLabel: "Page's exposure answer",
            computedAt: serverAnswered ? (input.serverExposures?.computed_at ?? null) : null,
            browserComputedAt: page !== null ? pageComputedAt(input.exposures) : null,
            difference: serverAnswered && page !== null && page !== server.result ? 'drift' : null,
            note,
        }
    }

    return [
        exposureCheck('zero_exposures', ['experiment', 'exposures'], null),
        exposureCheck('srm', ['exposures'], 'The finding needs p < 0.001.'),
        exposureCheck('bias_risk_multiple_excluded', ['exposures'], null),
        exposureCheck(
            'multiple_variants_share',
            ['exposures'],
            'The finding needs more than 5% and at least 5 users or groups in multiple variants, under Exclude only.'
        ),
    ]
}

/** One row per check, so a reader can see why the health panel shows what it shows. */
export function buildHealthDebugChecks(input: HealthDebugInput): HealthDebugCheck[] {
    return [
        flagStateCheck(input),
        serverOnlyCheck(input, 'split_changed_mid_run', splitChangedNote),
        serverOnlyCheck(input, 'bucketing_changed_mid_run', bucketingChangedNote),
        serverOnlyCheck(input, 'release_conditions_changed_mid_run', conditionsChangedNote),
        serverOnlyCheck(input, 'flag_variants_mismatch', null),
        serverOnlyCheck(input, 'forced_variant_release_condition', forcedVariantNote),
        serverOnlyCheck(input, 'new_flag_no_traffic', null),
        noMetricCheck(input),
        serverOnlyCheck(input, 'metric_event_not_ingested', metricEventNote, ['metrics', 'project']),
        serverOnlyCheck(input, 'exposure_criteria_cannot_match', exposureCriteriaNote, ['experiment', 'project']),
        ...exposureChecks(input),
    ]
}
