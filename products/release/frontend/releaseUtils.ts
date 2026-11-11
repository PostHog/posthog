import type { LemonTagType } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { ExperimentStatus } from '~/types'

import type { EarlyAccessFeatureApi } from 'products/early_access_features/frontend/generated/api.schemas'
import { getExperimentStatus } from 'products/experiments/frontend/experimentStatus'
import type { ExperimentBasicApi } from 'products/experiments/frontend/generated/api.schemas'
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
    upcoming: boolean
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

export interface ReleaseMarker {
    key: string
    date: string
    label: string
    flagKey: string
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
    reviewAfterDays: number
    nextDate: string | null
    spans: ReleaseSpan[]
    markers: ReleaseMarker[]
}

interface FlagGroup {
    properties?: unknown[] | null
    rollout_percentage?: number | null
}

interface FlagFilters {
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

export const STAGE_BADGE: Record<ReleaseStage, ReleaseBadgeVariant> = {
    planned: 'default',
    flag: 'default',
    experiment: 'info',
    early_access: 'warning',
    released: 'success',
}

export const STAGE_DOT: Record<ReleaseStage, 'default' | 'info' | 'warning' | 'success'> = {
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

export const isExperimentDraft = (experiment: ExperimentBasicApi): boolean =>
    getExperimentStatus(experiment as never) === ExperimentStatus.Draft

export const isExperimentDone = (experiment: ExperimentBasicApi): boolean => !!experiment.end_date

export function flagAudience(flag: FeatureFlagApi): string {
    const groups = flagFilters(flag).groups ?? []
    if (!flag.active) {
        return 'Nobody, the flag is disabled'
    }
    if (groups.length !== 1) {
        return `${groups.length} condition sets`
    }
    const percentage = groups[0].rollout_percentage ?? 100
    const filters = groups[0].properties?.length ?? 0
    return filters
        ? `${percentage}% of users that match ${filters} filter${filters > 1 ? 's' : ''}`
        : `${percentage}% of all users`
}

function isFullyRolledOut(flag: FeatureFlagApi): boolean {
    const filters = flagFilters(flag)
    const open = (filters.groups ?? []).some(
        (group) => !group.properties?.length && (group.rollout_percentage ?? 100) === 100
    )
    const variants = filters.multivariate?.variants ?? []
    return !!flag.active && open && (variants.length === 0 || variants.some((v) => v.rollout_percentage === 100))
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
const REVIEW_AFTER_DAYS = 14

const EARLY_ACCESS_NEXT: Record<string, { title: string; label: string }> = {
    concept: { title: 'Open the beta', label: 'Open early access' },
    alpha: { title: 'Move to beta', label: 'Open early access' },
    beta: { title: 'Move to general availability', label: 'Open early access' },
}

const CONCLUSION_LABEL: Record<string, string> = {
    won: 'The test variant won',
    lost: 'The test variant lost',
    inconclusive: 'The result was inconclusive',
    stopped_early: 'It was stopped early',
    invalid: 'The result was marked invalid',
}

function flagAudienceRow(flag: FeatureFlagApi, optIn = false): ReleaseFlagAudience {
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

export function buildReleaseRow(
    release: ReleaseDTOApi,
    allFlags: FeatureFlagApi[],
    allExperiments: ExperimentBasicApi[],
    allEarlyAccess: EarlyAccessFeatureApi[],
    allScheduled: ScheduledChangeApi[]
): ReleaseRow {
    const today = dayjs()
    const flags = release.feature_flag_ids
        .map((id) => allFlags.find((flag) => flag.id === id))
        .filter((flag): flag is FeatureFlagApi => !!flag)
    const missingFlagIds = release.feature_flag_ids.filter((id) => !allFlags.some((flag) => flag.id === id))
    const flagKeys = new Set(flags.map((flag) => flag.key))
    const flagById = new Map(flags.map((flag) => [String(flag.id), flag]))
    const experiments = allExperiments.filter((experiment) => flagKeys.has(experiment.feature_flag_key))
    const earlyAccess = allEarlyAccess.filter(
        (item) => item.feature_flag && flagKeys.has(item.feature_flag.key) && item.stage !== 'archived'
    )
    const changes = allScheduled
        .filter((change) => flagById.has(String(change.record_id)))
        .sort((a, b) => a.scheduled_at.localeCompare(b.scheduled_at))
    const scheduled = changes.filter((change) => !change.executed_at)

    const drafts = experiments.filter(isExperimentDraft)
    const done = experiments.filter(isExperimentDone)
    const running = experiments.filter((experiment) => !isExperimentDraft(experiment) && !isExperimentDone(experiment))
    const openEarlyAccess = earlyAccess.find((item) => item.stage !== 'general-availability')
    const released =
        flags.length > 0 && flags.every(isFullyRolledOut) && !running.length && !drafts.length && !openEarlyAccess

    const stage: ReleaseStage = released
        ? 'released'
        : running.length || drafts.length || done.length
          ? 'experiment'
          : openEarlyAccess
            ? 'early_access'
            : flags.length
              ? 'flag'
              : 'planned'

    const firstStart = running.map((experiment) => experiment.start_date as string).sort()[0]
    const runningDays = firstStart ? today.diff(dayjs(firstStart), 'day') + 1 : 0
    const lastDone = [...done].sort((a, b) => (b.end_date as string).localeCompare(a.end_date as string))[0]
    const optInKeys = new Set(earlyAccess.map((item) => item.feature_flag?.key))
    const audiences = flags.map((flag) => flagAudienceRow(flag, optInKeys.has(flag.key)))
    const mainAudience = audiences[0]

    let status = 'No feature flag yet'
    let headline = 'Not started'
    let detail = 'Link the feature flag that controls who gets this release.'
    if (released) {
        status = 'Rolled out to all users'
        headline = 'Rolled out to all users'
        detail = 'Every flag of this release serves it to everyone.'
    } else if (running.length) {
        status = `Experiment running, day ${runningDays}`
        headline = `Experiment running for ${runningDays} day${runningDays === 1 ? '' : 's'}`
        detail = `Started on ${dayjs(firstStart).format(DAY_FORMAT)}. Results are worth reading after about two weeks.`
    } else if (drafts.length) {
        status = 'Experiment in draft'
        headline = 'Experiment ready to launch'
        detail = `${drafts[0].name} is in draft. Nobody is in it yet.`
    } else if (lastDone) {
        status = 'Experiment complete'
        headline = `Experiment ended on ${dayjs(lastDone.end_date as string).format(DAY_FORMAT)}`
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
            detail: 'A flag controls who gets this release.',
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
            detail: `${running[0].name} has ${runningDays} days of data. Decide if the test variant should ship.`,
            label: 'Open results',
            to: urls.experiment(running[0].id),
            urgent: true,
        }
    } else if (running.length) {
        nextStep = {
            title: 'Let the experiment run',
            detail: `Check the results around ${dayjs(firstStart).add(REVIEW_AFTER_DAYS, 'day').format(DAY_FORMAT)}, when it has two weeks of data.`,
            secondaryLabel: 'Open experiment',
            secondaryTo: urls.experiment(running[0].id),
        }
    } else if (lastDone && !released && !lastDone.conclusion) {
        nextStep = {
            title: 'Record the result',
            detail: `${lastDone.name} ended without a recorded result. Record it so the team knows what to ship.`,
            label: 'Open experiment',
            to: urls.experiment(lastDone.id),
            urgent: true,
        }
    } else if (!released && flags.some((flag) => !isFullyRolledOut(flag)) && !openEarlyAccess) {
        const flag = flags.find((item) => !isFullyRolledOut(item)) ?? flags[0]
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
            title: EARLY_ACCESS_NEXT[openEarlyAccess.stage].title,
            detail: `${openEarlyAccess.name} is in ${openEarlyAccess.stage}. Move it on when the feedback is good.`,
            label: EARLY_ACCESS_NEXT[openEarlyAccess.stage].label,
            to: urls.earlyAccessFeature(openEarlyAccess.id),
        }
    } else if (released) {
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
    const testingDate = testingStarts[0]?.date
    const stageIndex = { planned: 0, flag: 1, experiment: 2, early_access: 2, released: 3 }[stage]
    const lifecycle: ReleaseLifecycleStep[] = [
        {
            key: 'planned' as const,
            label: 'Planned',
            date: [release.created_at, ...flags.map((flag) => flag.created_at)].sort()[0],
        },
        { key: 'flag' as const, label: 'Behind a flag', date: flags.map((flag) => flag.created_at).sort()[0] ?? null },
        {
            key: 'testing' as const,
            label: testingStarts[0]?.label ?? (experiments.length ? 'Experiment' : 'Testing'),
            date: testingDate ?? null,
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
            upcoming: false,
        },
        ...flags.map((flag) => ({
            key: `flag-${flag.id}`,
            date: flag.created_at,
            kind: 'flag' as const,
            title: `Flag ${flag.key} created`,
            href: urls.featureFlag(flag.id),
            upcoming: false,
        })),
        ...earlyAccess.map((item) => ({
            key: `ea-${item.id}`,
            date: item.created_at,
            kind: 'early_access' as const,
            title: `Early access opened: ${item.name}`,
            detail: `Now in ${item.stage}`,
            href: urls.earlyAccessFeature(item.id),
            upcoming: false,
        })),
        ...experiments.flatMap((experiment) => [
            ...(experiment.start_date
                ? [
                      {
                          key: `exp-start-${experiment.id}`,
                          date: experiment.start_date,
                          kind: 'experiment' as const,
                          title: `Experiment launched: ${experiment.name}`,
                          href: urls.experiment(experiment.id),
                          upcoming: false,
                      },
                  ]
                : [
                      {
                          key: `exp-draft-${experiment.id}`,
                          date: experiment.created_at,
                          kind: 'experiment' as const,
                          title: `Experiment drafted: ${experiment.name}`,
                          href: urls.experiment(experiment.id),
                          upcoming: false,
                      },
                  ]),
            ...(experiment.end_date
                ? [
                      {
                          key: `exp-end-${experiment.id}`,
                          date: experiment.end_date,
                          kind: 'experiment' as const,
                          title: `Experiment ended: ${experiment.name}`,
                          detail: experiment.conclusion
                              ? CONCLUSION_LABEL[experiment.conclusion]
                              : 'No result recorded',
                          href: urls.experiment(experiment.id),
                          upcoming: false,
                      },
                  ]
                : []),
        ]),
        ...changes.map((change) => ({
            key: `change-${change.id}`,
            date: change.executed_at ?? change.scheduled_at,
            kind: 'schedule' as const,
            title: scheduledChangeLabel(change),
            detail: flagById.get(String(change.record_id))?.key,
            href: urls.featureFlag(Number(change.record_id)),
            upcoming: !change.executed_at,
        })),
    ]

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
    if (flags.length) {
        spans.push({
            key: 'flag',
            kind: 'flag',
            from: flags
                .map((flag) => flag.created_at)
                .sort()[0]
                .slice(0, 10),
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
    for (const experiment of [...running, ...done]) {
        const from = (experiment.start_date as string).slice(0, 10)
        const finished = isExperimentDone(experiment)
        spans.push({
            key: `exp-${experiment.id}`,
            kind: finished ? 'experiment_done' : 'experiment',
            from,
            to: finished ? (experiment.end_date as string).slice(0, 10) : end,
            label: finished ? 'Experiment complete' : `Experiment, day ${today.diff(dayjs(from), 'day') + 1}`,
            href: urls.experiment(experiment.id),
        })
    }

    const markers = scheduled.map((change) => ({
        key: String(change.id),
        date: change.scheduled_at.slice(0, 10),
        label: scheduledChangeLabel(change),
        flagKey: flagById.get(String(change.record_id))?.key ?? '',
    }))

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
        reviewAfterDays: REVIEW_AFTER_DAYS,
        nextDate: markers[0]?.date ?? null,
        spans,
        markers,
    }
}
