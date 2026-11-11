import type { LemonTagType } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { hasDeniedApprovalRequest, isSchedulePaused } from 'scenes/feature-flags/scheduleOccurrences'
import { urls } from 'scenes/urls'

import { ExperimentStatus } from '~/types'

import type { EarlyAccessFeatureApi } from 'products/early_access_features/frontend/generated/api.schemas'
import { getExperimentStatus } from 'products/experiments/frontend/experimentStatus'
import type { ExperimentBasicApi } from 'products/experiments/frontend/generated/api.schemas'
import { isRulesV2FeatureFlagConfig } from 'products/feature_flags/frontend/featureFlagConfigFormat'
import type { FeatureFlagApi, ScheduledChangeApi } from 'products/feature_flags/frontend/generated/api.schemas'

import type { ReleaseDTOApi } from './generated/api.schemas'

export type ReleaseStage = 'planned' | 'flag' | 'experiment' | 'early_access' | 'released'

export interface ReleaseNextStep {
    title: string
    detail: string
    label?: string
    to?: string
    scheduleFlagId?: number
    secondaryLabel?: string
    secondaryTo?: string
    urgent?: boolean
}

export interface ReleaseLifecycleStep {
    key: 'planned' | 'flag' | 'testing' | 'released'
    label: string
    date: string | null
    state: 'done' | 'current' | 'upcoming'
}

export interface ReleaseFlagAudience {
    flag: FeatureFlagApi
    percent: number | null
    who: string
    summary: string
    variants: { key: string; percent: number }[]
}

export type ReleaseEventKind = 'release' | 'flag' | 'experiment' | 'early_access' | 'schedule'

export interface ReleaseEvent {
    key: string
    date: string
    kind: ReleaseEventKind
    title: string
    detail?: string
    href?: string
    upcoming?: boolean
}

export interface ReleaseSuggestion {
    key: string
    title: string
    detail: string
    label: string
    to: string
}

export interface ReleaseSpan {
    key: string
    kind: 'flag' | 'early_access' | 'experiment' | 'experiment_done'
    from: string
    to: string
    label?: string
    href: string
}

export interface ReleaseRow {
    id: string
    name: string
    description: string
    createdAt: string
    owner: ReleaseDTOApi['owner']
    missingFlagIds: number[]
    headline: string
    detail: string
    lifecycle: ReleaseLifecycleStep[]
    audiences: ReleaseFlagAudience[]
    events: ReleaseEvent[]
    suggestions: ReleaseSuggestion[]
    flags: FeatureFlagApi[]
    experiments: ExperimentBasicApi[]
    earlyAccess: EarlyAccessFeatureApi[]
    stage: ReleaseStage
    status: string
    audience: string
    nextStep: ReleaseNextStep | null
    needsDecision: boolean
    runningDays: number
    nextDate: string | null
    spans: ReleaseSpan[]
}

interface FlagGroup {
    properties?: unknown[] | null
    rollout_percentage?: number | null
    variant?: string | null
    aggregation_group_type_index?: number | null
}

interface FlagFilters {
    aggregation_group_type_index?: number | null
    groups?: FlagGroup[]
    multivariate?: { variants?: { key: string; rollout_percentage: number }[] } | null
}

export const STAGE_LABEL: Record<ReleaseStage, string> = {
    planned: 'Planned',
    flag: 'Behind a flag',
    experiment: 'Experiment',
    early_access: 'Early access',
    released: 'Released',
}

export type ReleaseBadgeVariant = 'default' | 'info' | 'destructive' | 'warning' | 'success' | 'completed'

export const STAGE_TONE: Record<ReleaseStage, 'default' | 'info' | 'warning' | 'success'> = {
    planned: 'default',
    flag: 'default',
    experiment: 'info',
    early_access: 'warning',
    released: 'success',
}

export function badgeVariantForTag(type: LemonTagType): ReleaseBadgeVariant {
    switch (type) {
        case 'success':
            return 'success'
        case 'warning':
        case 'caution':
            return 'warning'
        case 'danger':
            return 'destructive'
        case 'completion':
            return 'completed'
        case 'primary':
        case 'highlight':
        case 'info':
            return 'info'
        default:
            return 'default'
    }
}

const flagFilters = (flag: FeatureFlagApi): FlagFilters => (flag.filters ?? {}) as FlagFilters

const experimentStatus = (experiment: ExperimentBasicApi): ExperimentStatus => getExperimentStatus(experiment as never)

export const isExperimentDraft = (experiment: ExperimentBasicApi): boolean =>
    experimentStatus(experiment) === ExperimentStatus.Draft

export const isExperimentPaused = (experiment: ExperimentBasicApi): boolean =>
    experimentStatus(experiment) === ExperimentStatus.Paused

export const isExperimentDone = (experiment: ExperimentBasicApi): boolean =>
    experimentStatus(experiment) === ExperimentStatus.Stopped || !!experiment.end_date

export const isExperimentRunning = (experiment: ExperimentBasicApi): boolean =>
    !isExperimentDraft(experiment) && !isExperimentPaused(experiment) && !isExperimentDone(experiment)

const isRulesV2 = (flag: FeatureFlagApi): boolean => !!flag.filters && isRulesV2FeatureFlagConfig(flag.filters as never)

function isFullyRolledOut(flag: FeatureFlagApi): boolean {
    if (!flag.active || isRulesV2(flag)) {
        return false
    }
    const filters = flagFilters(flag)
    const groups = filters.groups ?? []
    const mixedTargets = groups.some(
        (group) =>
            group.aggregation_group_type_index != null &&
            group.aggregation_group_type_index !== filters.aggregation_group_type_index
    )
    if (mixedTargets) {
        return false
    }
    const open = groups.some((group) => !group.properties?.length && (group.rollout_percentage ?? 100) === 100)
    const variants = filters.multivariate?.variants ?? []
    if (!variants.length) {
        return open
    }
    const winner = variants.find((variant) => variant.rollout_percentage === 100)
    return open && !!winner && groups.every((group) => !group.variant || group.variant === winner.key)
}

export function scheduledChangeLabel(change: ScheduledChangeApi): string {
    const payload = (change.payload ?? {}) as { operation?: string; value?: unknown }
    const repeats = change.is_recurring && change.recurrence_interval ? `, repeats ${change.recurrence_interval}` : ''
    if (payload.operation === 'update_status') {
        return `${payload.value ? 'Enable' : 'Disable'} the flag${repeats}`
    }
    if (payload.operation === 'add_release_condition') {
        const groups = (payload.value as FlagFilters | undefined)?.groups ?? []
        const full = groups.some((group) => !group.properties?.length && group.rollout_percentage === 100)
        return `${full ? 'Roll out to 100%' : 'Add a release condition'}${repeats}`
    }
    return `Change the variants${repeats}`
}

const DAY_FORMAT = 'D MMM'
export const REVIEW_AFTER_DAYS = 14

const EARLY_ACCESS_NEXT: Record<string, string> = {
    concept: 'Open the beta',
    alpha: 'Move to beta',
    beta: 'Move to general availability',
}

const CONCLUSION_LABEL: Record<string, string> = {
    won: 'The test variant won',
    lost: 'The test variant lost',
    inconclusive: 'The result was inconclusive',
    stopped_early: 'It was stopped early',
    invalid: 'The result was marked invalid',
}

function flagAudienceRow(flag: FeatureFlagApi, optIn = false): ReleaseFlagAudience {
    if (isRulesV2(flag)) {
        return { flag, percent: null, who: 'Rules decide', summary: 'The flag rules decide who gets it', variants: [] }
    }
    const filters = flagFilters(flag)
    const groups = filters.groups ?? []
    const variants = (filters.multivariate?.variants ?? []).map((variant) => ({
        key: variant.key,
        percent: variant.rollout_percentage,
    }))
    if (!flag.active) {
        return {
            flag,
            percent: 0,
            who: 'Nobody, the flag is disabled',
            summary: 'The flag is disabled, so nobody gets it',
            variants,
        }
    }
    if (optIn && groups.every((group) => (group.rollout_percentage ?? 100) === 0)) {
        return {
            flag,
            percent: null,
            who: 'Only users who opt in',
            summary: 'Only users who opt in through early access get it',
            variants,
        }
    }
    if (groups.length === 1) {
        const percent = groups[0].rollout_percentage ?? 100
        const filterCount = groups[0].properties?.length ?? 0
        return {
            flag,
            percent,
            who: filterCount ? `Users that match ${filterCount} filter${filterCount > 1 ? 's' : ''}` : 'All users',
            summary: filterCount
                ? `${percent}% of users that match ${filterCount} filter${filterCount > 1 ? 's' : ''}`
                : `${percent}% of all users`,
            variants,
        }
    }
    return {
        flag,
        percent: null,
        who: `${groups.length} condition sets`,
        summary: `${groups.length} condition sets decide who gets it`,
        variants,
    }
}

export interface ReleaseIndex {
    flagsById: Map<number, FeatureFlagApi>
    experimentsByFlagKey: Map<string, ExperimentBasicApi[]>
    earlyAccessByFlagKey: Map<string, EarlyAccessFeatureApi[]>
    changesByFlagId: Map<string, ScheduledChangeApi[]>
}

function groupBy<T>(items: T[], key: (item: T) => string | undefined): Map<string, T[]> {
    const groups = new Map<string, T[]>()
    for (const item of items) {
        const value = key(item)
        if (value !== undefined) {
            groups.set(value, [...(groups.get(value) ?? []), item])
        }
    }
    return groups
}

export function buildReleaseIndex(
    flags: FeatureFlagApi[],
    experiments: ExperimentBasicApi[],
    earlyAccess: EarlyAccessFeatureApi[],
    scheduled: ScheduledChangeApi[]
): ReleaseIndex {
    return {
        flagsById: new Map(flags.filter((flag) => !flag.deleted).map((flag) => [flag.id, flag])),
        experimentsByFlagKey: groupBy(experiments, (experiment) => experiment.feature_flag_key),
        earlyAccessByFlagKey: groupBy(earlyAccess, (item) => item.feature_flag?.key),
        changesByFlagId: groupBy(scheduled, (change) => String(change.record_id)),
    }
}

export function buildReleaseRow(release: ReleaseDTOApi, index: ReleaseIndex): ReleaseRow {
    const today = dayjs()
    const flags = release.feature_flag_ids
        .map((id) => index.flagsById.get(id))
        .filter((flag): flag is FeatureFlagApi => !!flag)
    const missingFlagIds = release.feature_flag_ids.filter((id) => !index.flagsById.has(id))
    const flagById = new Map(flags.map((flag) => [String(flag.id), flag]))
    const experiments = flags.flatMap((flag) => index.experimentsByFlagKey.get(flag.key) ?? [])
    const earlyAccess = flags
        .flatMap((flag) => index.earlyAccessByFlagKey.get(flag.key) ?? [])
        .filter((item) => item.stage !== 'archived')
    const changes = flags
        .flatMap((flag) => index.changesByFlagId.get(String(flag.id)) ?? [])
        .filter(
            (change) =>
                !!change.executed_at ||
                (!isSchedulePaused(change as never) && !hasDeniedApprovalRequest(change as never))
        )
        .sort((a, b) => a.scheduled_at.localeCompare(b.scheduled_at))
    const firstFlagCreated = flags.map((flag) => flag.created_at).sort()[0] ?? null

    const drafts = experiments.filter(isExperimentDraft)
    const done = experiments.filter(isExperimentDone)
    const running = experiments.filter(isExperimentRunning)
    const paused = experiments.filter(isExperimentPaused)
    const openEarlyAccess = earlyAccess.find((item) => item.stage !== 'general-availability')
    const flagsArchived = flags.length > 0 && flags.every((flag) => flag.archived)
    const released =
        flagsArchived ||
        (flags.length > 0 &&
            flags.every(isFullyRolledOut) &&
            !running.length &&
            !paused.length &&
            !drafts.length &&
            !openEarlyAccess)

    const stage: ReleaseStage = released
        ? 'released'
        : running.length || paused.length || drafts.length || done.length
          ? 'experiment'
          : openEarlyAccess
            ? 'early_access'
            : flags.length
              ? 'flag'
              : 'planned'

    const current = [...running].sort((a, b) => (a.start_date as string).localeCompare(b.start_date as string))[0]
    const firstStart = current?.start_date
    const runningDays = firstStart ? today.diff(dayjs(firstStart), 'day') + 1 : 0
    const lastDone = [...done].sort((a, b) => (b.end_date ?? '').localeCompare(a.end_date ?? ''))[0]
    const optInKeys = new Set(earlyAccess.map((item) => item.feature_flag?.key))
    const audiences = flags.map((flag) => flagAudienceRow(flag, optInKeys.has(flag.key)))
    const mainAudience = audiences[0]

    let status = 'No feature flag yet'
    let headline = 'Not started'
    let detail = 'Link the feature flag that controls who gets this release.'
    if (released) {
        status = 'Rolled out to all users'
        headline = 'Rolled out to all users'
        detail = flagsArchived
            ? 'The flags of this release are archived. Nothing is left to do.'
            : 'Every flag of this release serves it to everyone.'
    } else if (running.length) {
        status = `Experiment running, day ${runningDays}`
        headline = `Experiment running for ${runningDays} day${runningDays === 1 ? '' : 's'}`
        detail = `Started on ${dayjs(firstStart).format(DAY_FORMAT)}. Results are worth reading after about two weeks.`
    } else if (paused.length) {
        status = 'Experiment paused'
        headline = 'Experiment paused'
        detail = `${paused[0].name} is paused, so it collects no new data.`
    } else if (drafts.length) {
        status = 'Experiment in draft'
        headline = 'Experiment ready to launch'
        detail = `${drafts[0].name} is in draft. Nobody is in it yet.`
    } else if (lastDone) {
        status = 'Experiment complete'
        headline = lastDone.end_date
            ? `Experiment ended on ${dayjs(lastDone.end_date).format(DAY_FORMAT)}`
            : 'Experiment stopped'
        detail = lastDone.conclusion
            ? `${CONCLUSION_LABEL[lastDone.conclusion] ?? lastDone.conclusion}.${lastDone.conclusion_comment ? ` ${lastDone.conclusion_comment}` : ''}`
            : 'No result is recorded on the experiment yet.'
    } else if (openEarlyAccess) {
        status = `Early access, ${openEarlyAccess.stage}`
        headline = `In early access, ${openEarlyAccess.stage}`
        detail = 'Users can opt in to it before everyone gets it.'
    } else if (flags.length) {
        status = 'Behind a flag'
        headline = 'Behind a flag'
        detail = mainAudience ? `${mainAudience.summary}.` : ''
    }

    let nextStep: ReleaseNextStep | null = null
    if (!flags.length) {
        nextStep = {
            title: 'Link a feature flag',
            detail: 'Pick the flag your code checks for this change, or create one.',
        }
    } else if (drafts.length && !running.length) {
        nextStep = {
            title: 'Launch the experiment',
            detail: `${drafts[0].name} is ready. Launch it to start collecting results.`,
            label: 'Open experiment',
            to: urls.experiment(drafts[0].id),
            urgent: true,
        }
    } else if (running.length && runningDays >= REVIEW_AFTER_DAYS - 2) {
        nextStep = {
            title: 'Review the results',
            detail: `${current.name} has ${runningDays} days of data. Decide if the test variant should ship.`,
            label: 'Open results',
            to: urls.experiment(current.id),
            urgent: true,
        }
    } else if (running.length) {
        nextStep = {
            title: 'Let the experiment run',
            detail: `Check the results around ${dayjs(firstStart).add(REVIEW_AFTER_DAYS, 'day').format(DAY_FORMAT)}, when it has two weeks of data.`,
            secondaryLabel: 'Open experiment',
            secondaryTo: urls.experiment(current.id),
        }
    } else if (paused.length) {
        nextStep = {
            title: 'Resume or end the experiment',
            detail: `${paused[0].name} is paused. Resume it to collect more data, or end it and record the result.`,
            label: 'Open experiment',
            to: urls.experiment(paused[0].id),
            urgent: true,
        }
    } else if (lastDone && !released && !lastDone.conclusion) {
        nextStep = {
            title: 'Record the result',
            detail: `${lastDone.name} ended without a recorded result. Record it so the team knows what to ship.`,
            label: 'Open experiment',
            to: urls.experiment(lastDone.id),
            urgent: true,
        }
    } else if (!released && !openEarlyAccess && flags.some((flag) => !isFullyRolledOut(flag) && !isRulesV2(flag))) {
        const flag = flags.find((item) => !isFullyRolledOut(item) && !isRulesV2(item)) ?? flags[0]
        nextStep = {
            title: lastDone ? 'Roll out the winner' : 'Roll out to more users',
            detail: lastDone
                ? `Not everyone gets the winning variant yet. Roll ${flag.key} out to all users now or on a date.`
                : `Not everyone gets it yet. Widen the release conditions of ${flag.key}, or schedule a rollout to everyone.`,
            label: 'Schedule rollout',
            scheduleFlagId: flag.id,
            secondaryLabel: 'Open flag',
            secondaryTo: urls.featureFlag(flag.id),
            urgent: !!lastDone,
        }
    } else if (openEarlyAccess && EARLY_ACCESS_NEXT[openEarlyAccess.stage]) {
        nextStep = {
            title: EARLY_ACCESS_NEXT[openEarlyAccess.stage],
            detail: `${openEarlyAccess.name} is in ${openEarlyAccess.stage}. Move it on when the feedback is good.`,
            label: 'Open early access',
            to: urls.earlyAccessFeature(openEarlyAccess.id),
        }
    } else if (released && !flagsArchived) {
        nextStep = {
            title: 'Clean up the flag',
            detail: 'Everyone gets the release now. Remove the flag check from your code, then archive the flag.',
            label: 'Open flag',
            to: urls.featureFlag(flags[0].id),
        }
    }

    const testingStarts = [
        ...experiments
            .filter((experiment) => experiment.start_date)
            .map((experiment) => ({ date: experiment.start_date as string, label: 'Experiment' })),
        ...earlyAccess.map((item) => ({ date: item.created_at, label: 'Early access' })),
    ].sort((a, b) => a.date.localeCompare(b.date))
    const stageIndex = { planned: 0, flag: 1, experiment: 2, early_access: 2, released: 3 }[stage]
    const lifecycle: ReleaseLifecycleStep[] = [
        {
            key: 'planned' as const,
            label: 'Planned',
            date: firstFlagCreated && firstFlagCreated < release.created_at ? firstFlagCreated : release.created_at,
        },
        { key: 'flag' as const, label: 'Behind a flag', date: firstFlagCreated },
        {
            key: 'testing' as const,
            label: testingStarts[0]?.label ?? (experiments.length ? 'Experiment' : 'Testing'),
            date: testingStarts[0]?.date ?? null,
        },
        { key: 'released' as const, label: 'Rolled out', date: null },
    ].map((step, index) => ({
        ...step,
        date: index <= stageIndex ? step.date : null,
        state:
            index < stageIndex || (released && index === stageIndex)
                ? 'done'
                : index === stageIndex
                  ? 'current'
                  : 'upcoming',
    }))

    const events: ReleaseEvent[] = [
        {
            key: 'release',
            date: release.created_at,
            kind: 'release',
            title: flags.length ? 'Grouped into this release' : 'Release created',
        },
        ...flags.map((flag) => ({
            key: `flag-${flag.id}`,
            date: flag.created_at,
            kind: 'flag' as const,
            title: `Flag ${flag.key} created`,
            href: urls.featureFlag(flag.id),
        })),
        ...earlyAccess.map((item) => ({
            key: `ea-${item.id}`,
            date: item.created_at,
            kind: 'early_access' as const,
            title: `Early access opened: ${item.name}`,
            detail: `Now in ${item.stage}`,
            href: urls.earlyAccessFeature(item.id),
        })),
    ]
    for (const experiment of experiments) {
        const href = urls.experiment(experiment.id)
        events.push({
            key: `exp-start-${experiment.id}`,
            date: experiment.start_date ?? experiment.created_at,
            kind: 'experiment',
            title: `${experiment.start_date ? 'Experiment launched' : 'Experiment drafted'}: ${experiment.name}`,
            href,
        })
        if (experiment.end_date) {
            events.push({
                key: `exp-end-${experiment.id}`,
                date: experiment.end_date,
                kind: 'experiment',
                title: `Experiment ended: ${experiment.name}`,
                detail: experiment.conclusion ? CONCLUSION_LABEL[experiment.conclusion] : 'No result recorded',
                href,
            })
        }
    }
    for (const change of changes) {
        events.push({
            key: `change-${change.id}`,
            date: change.executed_at ?? change.scheduled_at,
            kind: 'schedule',
            title: change.failure_reason
                ? `Not applied: ${scheduledChangeLabel(change)}`
                : scheduledChangeLabel(change),
            detail: change.failure_reason
                ? `${flagById.get(String(change.record_id))?.key}, the change failed`
                : flagById.get(String(change.record_id))?.key,
            href: urls.featureFlag(Number(change.record_id)),
            upcoming: !change.executed_at && !change.failure_reason,
        })
    }

    const suggestions: ReleaseSuggestion[] = []
    if (flags.length && !experiments.length && !released) {
        suggestions.push({
            key: 'experiment',
            title: 'Measure the impact',
            detail: 'Run an experiment on this flag to see if the release helps.',
            label: 'New experiment',
            to: urls.experiment('new'),
        })
    }
    if (flags.length && !earlyAccess.length && !released && stage === 'flag') {
        suggestions.push({
            key: 'early-access',
            title: 'Let users opt in first',
            detail: 'Interested users try the release before everyone gets it.',
            label: 'New early access feature',
            to: urls.earlyAccessFeature('new'),
        })
    }

    const end = today.format('YYYY-MM-DD')
    const spans: ReleaseSpan[] = []
    if (firstFlagCreated) {
        spans.push({
            key: 'flag',
            kind: 'flag',
            from: firstFlagCreated.slice(0, 10),
            to: end,
            href: urls.featureFlag(flags[0].id),
        })
    }
    for (const item of earlyAccess) {
        spans.push({
            key: `ea-${item.id}`,
            kind: 'early_access',
            from: item.created_at.slice(0, 10),
            to: end,
            href: urls.earlyAccessFeature(item.id),
        })
    }
    for (const experiment of [...running, ...paused, ...done]) {
        if (!experiment.start_date) {
            continue
        }
        const from = experiment.start_date.slice(0, 10)
        const finished = isExperimentDone(experiment)
        spans.push({
            key: `exp-${experiment.id}`,
            kind: finished ? 'experiment_done' : 'experiment',
            from,
            to: finished && experiment.end_date ? experiment.end_date.slice(0, 10) : end,
            label: finished
                ? 'Experiment complete'
                : isExperimentPaused(experiment)
                  ? 'Experiment paused'
                  : `Experiment, day ${today.diff(dayjs(from), 'day') + 1}`,
            href: urls.experiment(experiment.id),
        })
    }

    const audience = openEarlyAccess
        ? 'Users who opt in'
        : running.length
          ? 'Experiment participants'
          : mainAudience
            ? mainAudience.summary
            : 'Nobody yet'

    return {
        id: release.id,
        name: release.name,
        description: release.description,
        createdAt: release.created_at,
        owner: release.owner,
        missingFlagIds,
        headline,
        detail,
        lifecycle,
        audiences,
        events,
        suggestions,
        flags,
        experiments,
        earlyAccess,
        stage,
        status,
        audience,
        nextStep,
        needsDecision: !flags.length || !!nextStep?.urgent,
        runningDays,
        nextDate: events.find((event) => event.upcoming)?.date.slice(0, 10) ?? null,
        spans,
    }
}
