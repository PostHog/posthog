import { combineUrl } from 'kea-router'

import type { LemonTagType } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { hasDeniedApprovalRequest, isSchedulePaused } from 'scenes/feature-flags/scheduleOccurrences'
import { urls } from 'scenes/urls'

import { ExperimentStatus } from '~/types'

import type { EarlyAccessFeatureApi } from 'products/early_access_features/frontend/generated/api.schemas'
import { getExperimentStatus } from 'products/experiments/frontend/experimentStatus'
import type { ExperimentBasicApi } from 'products/experiments/frontend/generated/api.schemas'
import { isV1FeatureFlagConfig } from 'products/feature_flags/frontend/featureFlagConfigFormat'
import type { FeatureFlagApi, ScheduledChangeApi } from 'products/feature_flags/frontend/generated/api.schemas'
import {
    NAME_PREFILL_PARAM,
    SOURCE_PREFILL_PARAM,
    SOURCE_RECORD_PREFILL_PARAM,
} from 'products/workflows/frontend/Broadcasts/broadcastAudiencePrefill'
import type { SendCalendarFlowApi } from 'products/workflows/frontend/generated/api.schemas'
import { scheduleSendTimes } from 'products/workflows/frontend/SendCalendar/sendCalendarUtils'

import type { LinkedBroadcastDTOApi, LinkedSendDTOApi, ReleaseDTOApi } from './generated/api.schemas'

export type ReleaseStage = 'planned' | 'flag' | 'experiment' | 'early_access' | 'released' | 'ended'

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

export type ReleaseEventKind = 'release' | 'flag' | 'experiment' | 'early_access' | 'schedule' | 'broadcast'

export const CALENDAR_DAYS_BEFORE = 17
export const CALENDAR_DAYS_AFTER = 60

export interface ReleaseEvent {
    key: string
    date: string
    kind: ReleaseEventKind
    title: string
    detail?: string
    href?: string
    upcoming?: boolean
    flagId?: number
}

export interface ReleaseSuggestion {
    key: string
    title: string
    detail: string
    label: string
    to: string
}

export const releaseSourceRecord = (releaseId: string): string => `release:${releaseId}`

export type ReleaseSpanTone = 'default' | 'info' | 'warning' | 'success'

export interface ReleaseSpan {
    key: string
    kind: 'flag' | 'early_access' | 'experiment' | 'experiment_done'
    tone?: ReleaseSpanTone
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
    broadcasts: LinkedBroadcastDTOApi[]
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
    early_exit?: boolean
    feature_enrollment?: boolean
    holdout?: { exclusion_percentage?: number } | null
}

export const STAGE_LABEL: Record<ReleaseStage, string> = {
    planned: 'Planned',
    flag: 'Behind a flag',
    experiment: 'Experiment',
    early_access: 'Early access',
    released: 'Released',
    ended: 'Ended',
}

export type ReleaseBadgeVariant = 'default' | 'info' | 'destructive' | 'warning' | 'success' | 'completed'

export const STAGE_TONE: Record<ReleaseStage, 'default' | 'info' | 'warning' | 'success'> = {
    planned: 'default',
    flag: 'default',
    experiment: 'info',
    early_access: 'warning',
    released: 'success',
    ended: 'default',
}

export const STAGE_COLOR_VARS =
    '[--release-flag:#1d4aff] [--release-experiment:#c0339a] [--release-early-access:#a87400] [--release-released:#1f7a4a] dark:[--release-flag:#6b8bff] dark:[--release-experiment:#e45bb8] dark:[--release-early-access:#e8ac10] dark:[--release-released:#3fb878]'

export const STAGE_COLOR: Record<ReleaseStage, string> = {
    planned: 'var(--muted-foreground)',
    flag: 'var(--release-flag)',
    experiment: 'var(--release-experiment)',
    early_access: 'var(--release-early-access)',
    released: 'var(--release-released)',
    ended: 'var(--muted-foreground)',
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

const isV1 = (flag: FeatureFlagApi): boolean => !flag.filters || isV1FeatureFlagConfig(flag.filters as never)

const holdoutPercent = (flag: FeatureFlagApi): number => flagFilters(flag).holdout?.exclusion_percentage ?? 0

const canWidenRollout = (flag: FeatureFlagApi): boolean =>
    isV1(flag) && !flagFilters(flag).feature_enrollment && !isFullyRolledOut(flag)

const isOpenGroup = (group: FlagGroup): boolean => !group.properties?.length

function isFullyRolledOut(flag: FeatureFlagApi): boolean {
    if (!flag.active || !isV1(flag)) {
        return false
    }
    const filters = flagFilters(flag)
    if (filters.feature_enrollment || holdoutPercent(flag) > 0) {
        return false
    }
    const groups = filters.groups ?? []
    const mixedTargets = groups.some(
        (group) =>
            group.aggregation_group_type_index != null &&
            group.aggregation_group_type_index !== filters.aggregation_group_type_index
    )
    if (mixedTargets) {
        return false
    }
    const fullGroup = (group: FlagGroup): boolean => (group.rollout_percentage ?? 100) === 100
    const firstOpen = groups.findIndex(isOpenGroup)
    const open = filters.early_exit
        ? firstOpen >= 0 && groups.slice(0, firstOpen + 1).every(fullGroup)
        : groups.some((group) => isOpenGroup(group) && fullGroup(group))
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

const ENROLLING_EARLY_ACCESS_STAGES = new Set(['alpha', 'beta'])

export const isEnrollingEarlyAccess = (item: EarlyAccessFeatureApi): boolean =>
    ENROLLING_EARLY_ACCESS_STAGES.has(item.stage)

const EARLY_ACCESS_NEXT: Record<string, string> = {
    draft: 'Launch early access',
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
    const audience = conditionAudience(flag, optIn)
    const holdout = holdoutPercent(flag)
    if (!holdout) {
        return audience
    }
    return {
        ...audience,
        percent: audience.percent === null ? null : Math.round(audience.percent * (100 - holdout)) / 100,
        summary: `${audience.summary}, except a ${holdout}% holdout`,
    }
}

function conditionAudience(flag: FeatureFlagApi, optIn: boolean): ReleaseFlagAudience {
    const filters = flagFilters(flag)
    const variants = isV1(flag)
        ? (filters.multivariate?.variants ?? []).map((variant) => ({
              key: variant.key,
              percent: variant.rollout_percentage,
          }))
        : []
    if (!flag.active) {
        return {
            flag,
            percent: 0,
            who: 'Nobody, the flag is disabled',
            summary: 'The flag is disabled, so nobody gets it',
            variants,
        }
    }
    if (!isV1(flag)) {
        return { flag, percent: null, who: 'Rules decide', summary: 'The flag rules decide who gets it', variants: [] }
    }
    const groups = filters.groups ?? []
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
        const noun =
            (groups[0].aggregation_group_type_index ?? filters.aggregation_group_type_index) != null
                ? 'groups'
                : 'users'
        const matching = `${noun} that match ${filterCount} filter${filterCount > 1 ? 's' : ''}`
        return {
            flag,
            percent,
            who: filterCount ? matching.charAt(0).toUpperCase() + matching.slice(1) : `All ${noun}`,
            summary: filterCount ? `${percent}% of ${matching}` : `${percent}% of all ${noun}`,
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

function scheduleEvents(change: ScheduledChangeApi, flagKey: string | undefined): ReleaseEvent[] {
    const label = scheduledChangeLabel(change)
    const href = urls.featureFlag(Number(change.record_id))
    const denied = hasDeniedApprovalRequest(change as never)
    const expired = !!change.end_date && dayjs(change.end_date).isBefore(dayjs())
    const live = !isSchedulePaused(change as never) && !denied && !expired
    const base = { kind: 'schedule' as const, href, flagId: Number(change.record_id) }

    if (change.is_recurring) {
        const events: ReleaseEvent[] = []
        if (change.last_executed_at) {
            events.push({
                ...base,
                key: `change-${change.id}-last`,
                date: change.last_executed_at,
                title: `Last run: ${label}`,
                detail: flagKey,
            })
        }
        if (!change.executed_at && !live) {
            return events
        }
        events.push(
            change.executed_at
                ? {
                      ...base,
                      key: `change-${change.id}`,
                      date: change.executed_at,
                      title: `Repeating change ended: ${label}`,
                      detail: flagKey,
                  }
                : {
                      ...base,
                      key: `change-${change.id}`,
                      date: change.scheduled_at,
                      title: label,
                      detail: flagKey,
                      upcoming: true,
                  }
        )
        return events
    }

    if (!change.executed_at) {
        if (!live) {
            return []
        }
        const pending = change.change_request?.state === 'pending'
        const retrying = !!change.failure_reason
        return [
            {
                ...base,
                key: `change-${change.id}`,
                date: change.scheduled_at,
                title: pending ? `Needs approval: ${label}` : retrying ? `Retrying: ${label}` : label,
                detail: pending
                    ? `${flagKey}, skipped if nobody approves it in time`
                    : retrying
                      ? `${flagKey}, the last attempt failed and PostHog tries again`
                      : flagKey,
                href: pending && change.change_request ? urls.approval(change.change_request.id) : href,
                upcoming: true,
            },
        ]
    }

    return [
        {
            ...base,
            key: `change-${change.id}`,
            date: change.executed_at,
            title: denied || change.failure_reason ? `Not applied: ${label}` : label,
            detail: denied
                ? `${flagKey}, the approval was not given`
                : change.failure_reason
                  ? `${flagKey}, the change failed`
                  : flagKey,
        },
    ]
}

export interface ReleaseMessaging {
    broadcasts: LinkedBroadcastDTOApi[]
    sends: SendCalendarFlowApi[]
    runs: Record<string, LinkedSendDTOApi[]>
}

const EMPTY_MESSAGING: ReleaseMessaging = { broadcasts: [], sends: [], runs: {} }

const SEND_TITLE: Record<string, string> = {
    completed: 'Broadcast sent',
    partially_failed: 'Broadcast partly sent',
    failed: 'Broadcast failed',
    cancelled: 'Broadcast cancelled',
}

function runEvents(broadcastId: string, name: string, runs: LinkedSendDTOApi[]): ReleaseEvent[] {
    return runs.map((run) => ({
        key: `send-${run.id}`,
        date: run.created_at,
        kind: 'broadcast' as const,
        title: `${SEND_TITLE[run.status] ?? 'Broadcast sending'}: ${name}`,
        detail: run.status === 'completed' ? undefined : `The send is ${run.status.replace('_', ' ')}`,
        href: urls.broadcast(broadcastId),
    }))
}

function upcomingSendEvents(flow: SendCalendarFlowApi, now: dayjs.Dayjs): ReleaseEvent[] {
    const range = { start: now, end: now.startOf('day').add(CALENDAR_DAYS_AFTER + 1, 'day') }
    return flow.schedules
        .filter((schedule) => schedule.status !== 'paused')
        .flatMap((schedule) =>
            scheduleSendTimes(schedule, range).map((time) => ({
                key: `send-schedule-${schedule.id}-${time.valueOf()}`,
                date: time.toISOString(),
                kind: 'broadcast' as const,
                title: `Broadcast scheduled: ${flow.name || 'Untitled broadcast'}`,
                detail: 'Scheduled to send',
                href: urls.broadcast(flow.id),
                upcoming: true,
            }))
        )
}

function sendEventsByBroadcast(messaging: ReleaseMessaging): Map<string, ReleaseEvent[]> {
    const now = dayjs()
    const names = new Map(
        messaging.broadcasts.map((broadcast) => [broadcast.id, broadcast.name || 'Untitled broadcast'])
    )
    const events = new Map<string, ReleaseEvent[]>()
    const runsByBroadcast = new Map<string, Map<string, LinkedSendDTOApi>>()
    const addRuns = (broadcastId: string, runs: readonly LinkedSendDTOApi[]): void => {
        const known = runsByBroadcast.get(broadcastId) ?? new Map<string, LinkedSendDTOApi>()
        for (const run of runs) {
            known.set(run.id, run)
        }
        runsByBroadcast.set(broadcastId, known)
    }
    for (const [broadcastId, runs] of Object.entries(messaging.runs)) {
        addRuns(broadcastId, runs)
    }
    for (const flow of messaging.sends) {
        addRuns(flow.id, flow.batch_jobs)
    }
    for (const [broadcastId, runs] of runsByBroadcast) {
        events.set(
            broadcastId,
            runEvents(broadcastId, names.get(broadcastId) ?? 'Untitled broadcast', [...runs.values()])
        )
    }
    for (const flow of messaging.sends) {
        events.set(flow.id, [...(events.get(flow.id) ?? []), ...upcomingSendEvents(flow, now)])
    }
    return events
}

export interface ReleaseIndex {
    flagsById: Map<number, FeatureFlagApi>
    experimentsByFlagKey: Map<string, ExperimentBasicApi[]>
    earlyAccessByFlagKey: Map<string, EarlyAccessFeatureApi[]>
    changesByFlagId: Map<string, ScheduledChangeApi[]>
    scheduleEventsByFlagId: Map<number, ReleaseEvent[]>
    broadcastsById: Map<string, LinkedBroadcastDTOApi>
    sendEventsByBroadcastId: Map<string, ReleaseEvent[]>
    complete: boolean
    resolvedFlagIds: Set<number>
    unknownFlagIds: Set<number>
}

function groupBy<T>(items: T[], key: (item: T) => string | undefined): Map<string, T[]> {
    const groups = new Map<string, T[]>()
    for (const item of items) {
        const value = key(item)
        if (value !== undefined) {
            const group = groups.get(value)
            if (group) {
                group.push(item)
            } else {
                groups.set(value, [item])
            }
        }
    }
    return groups
}

export interface ReleaseIndexStatus {
    complete: boolean
    resolvedFlagIds: number[]
    unknownFlagIds: number[]
}

export type ScheduleIndex = Pick<ReleaseIndex, 'changesByFlagId' | 'scheduleEventsByFlagId'>

export function indexFlags(flags: FeatureFlagApi[]): Map<number, FeatureFlagApi> {
    return new Map(flags.filter((flag) => !flag.deleted).map((flag) => [flag.id, flag]))
}

export function indexExperiments(experiments: ExperimentBasicApi[]): Map<string, ExperimentBasicApi[]> {
    return groupBy(experiments, (experiment) => experiment.feature_flag_key)
}

export function indexEarlyAccess(earlyAccess: EarlyAccessFeatureApi[]): Map<string, EarlyAccessFeatureApi[]> {
    return groupBy(earlyAccess, (item) => item.feature_flag?.key)
}

export function indexSchedules(flags: FeatureFlagApi[], scheduled: ScheduledChangeApi[]): ScheduleIndex {
    const changesByFlagId = groupBy(scheduled, (change) => String(change.record_id))
    return {
        changesByFlagId,
        scheduleEventsByFlagId: new Map(
            flags.map((flag) => [
                flag.id,
                (changesByFlagId.get(String(flag.id)) ?? []).flatMap((change) => scheduleEvents(change, flag.key)),
            ])
        ),
    }
}

export function composeReleaseIndex(
    parts: {
        flagsById: Map<number, FeatureFlagApi>
        experimentsByFlagKey: Map<string, ExperimentBasicApi[]>
        earlyAccessByFlagKey: Map<string, EarlyAccessFeatureApi[]>
        schedules: ScheduleIndex
    },
    status: ReleaseIndexStatus,
    messaging: ReleaseMessaging = EMPTY_MESSAGING
): ReleaseIndex {
    return {
        broadcastsById: new Map(messaging.broadcasts.map((broadcast) => [broadcast.id, broadcast])),
        sendEventsByBroadcastId: sendEventsByBroadcast(messaging),
        flagsById: parts.flagsById,
        experimentsByFlagKey: parts.experimentsByFlagKey,
        earlyAccessByFlagKey: parts.earlyAccessByFlagKey,
        ...parts.schedules,
        complete: status.complete,
        resolvedFlagIds: new Set(status.resolvedFlagIds),
        unknownFlagIds: new Set(status.unknownFlagIds),
    }
}

export function buildReleaseIndex(
    flags: FeatureFlagApi[],
    experiments: ExperimentBasicApi[],
    earlyAccess: EarlyAccessFeatureApi[],
    scheduled: ScheduledChangeApi[],
    status: ReleaseIndexStatus,
    messaging: ReleaseMessaging = EMPTY_MESSAGING
): ReleaseIndex {
    return composeReleaseIndex(
        {
            flagsById: indexFlags(flags),
            experimentsByFlagKey: indexExperiments(experiments),
            earlyAccessByFlagKey: indexEarlyAccess(earlyAccess),
            schedules: indexSchedules(flags, scheduled),
        },
        status,
        messaging
    )
}

interface ReleaseFacts {
    today: dayjs.Dayjs
    flags: FeatureFlagApi[]
    unloadedFlagIds: number[]
    missingFlagIds: number[]
    hasHiddenFlags: boolean
    pendingFlags: boolean
    complete: boolean
    experiments: ExperimentBasicApi[]
    earlyAccess: EarlyAccessFeatureApi[]
    broadcasts: LinkedBroadcastDTOApi[]
    drafts: ExperimentBasicApi[]
    done: ExperimentBasicApi[]
    running: ExperimentBasicApi[]
    paused: ExperimentBasicApi[]
    openEarlyAccess: EarlyAccessFeatureApi | undefined
    prelaunchEarlyAccess: EarlyAccessFeatureApi | undefined
    ended: boolean
    released: boolean
    finished: boolean
    current: ExperimentBasicApi | undefined
    firstStart: string | null | undefined
    runningDays: number
    lastDone: ExperimentBasicApi | undefined
    audiences: ReleaseFlagAudience[]
    audienceSummary: string | undefined
    firstFlagCreated: string | null
}

function isReleased(facts: Omit<ReleaseFacts, 'released' | 'finished'>): boolean {
    const { ended, complete, flags, unloadedFlagIds, running, paused, drafts, openEarlyAccess } = facts
    return (
        !ended &&
        complete &&
        flags.length > 0 &&
        !unloadedFlagIds.length &&
        flags.every(isFullyRolledOut) &&
        !running.length &&
        !paused.length &&
        !drafts.length &&
        !openEarlyAccess
    )
}

function releaseFacts(release: ReleaseDTOApi, index: ReleaseIndex): ReleaseFacts {
    const today = dayjs()
    const flags = release.feature_flag_ids
        .map((id) => index.flagsById.get(id))
        .filter((flag): flag is FeatureFlagApi => !!flag)
    const unloadedFlagIds = release.feature_flag_ids.filter((id) => !index.flagsById.has(id))
    const missingFlagIds = unloadedFlagIds.filter((id) => index.resolvedFlagIds.has(id))
    const complete =
        index.complete &&
        !release.has_hidden_flags &&
        missingFlagIds.length === unloadedFlagIds.length &&
        !flags.some((flag) => index.unknownFlagIds.has(flag.id))
    const experiments = flags
        .flatMap((flag) => index.experimentsByFlagKey.get(flag.key) ?? [])
        .filter((experiment) => !experiment.archived || isExperimentDone(experiment))
    const earlyAccess = flags.flatMap((flag) => index.earlyAccessByFlagKey.get(flag.key) ?? [])
    const running = experiments.filter(isExperimentRunning)
    const done = experiments.filter(isExperimentDone)
    const openEarlyAccess = earlyAccess.find(isEnrollingEarlyAccess)
    const current = [...running].sort((a, b) => (a.start_date as string).localeCompare(b.start_date as string))[0]
    const firstStart = current?.start_date
    const optInKeys = new Set(earlyAccess.filter(isEnrollingEarlyAccess).map((item) => item.feature_flag?.key))
    const audiences = flags.map((flag) =>
        flagAudienceRow(flag, optInKeys.has(flag.key) || !!flagFilters(flag).feature_enrollment)
    )
    const base = {
        today,
        flags,
        unloadedFlagIds,
        missingFlagIds,
        hasHiddenFlags: release.has_hidden_flags,
        pendingFlags: unloadedFlagIds.some((id) => !index.resolvedFlagIds.has(id)),
        complete,
        experiments,
        earlyAccess,
        broadcasts: release.broadcast_ids
            .map((id) => index.broadcastsById.get(id))
            .filter((broadcast): broadcast is LinkedBroadcastDTOApi => !!broadcast),
        drafts: experiments.filter(isExperimentDraft),
        done,
        running,
        paused: experiments.filter(isExperimentPaused),
        openEarlyAccess,
        prelaunchEarlyAccess: openEarlyAccess
            ? undefined
            : earlyAccess.find((item) => item.stage === 'draft' || item.stage === 'concept'),
        ended:
            flags.length > 0 &&
            !unloadedFlagIds.length &&
            !release.has_hidden_flags &&
            flags.every((flag) => flag.archived),
        current,
        firstStart,
        runningDays: firstStart ? today.diff(dayjs(firstStart), 'day') + 1 : 0,
        lastDone: [...done].sort((a, b) => (b.end_date ?? '').localeCompare(a.end_date ?? ''))[0],
        audiences,
        audienceSummary:
            new Set(audiences.map((audience) => audience.summary)).size > 1
                ? audiences.every((audience) => audience.percent !== null)
                    ? `${audiences.filter((audience) => isFullyRolledOut(audience.flag)).length} of ${audiences.length} flags reach everyone`
                    : `Differs across ${audiences.length} flags`
                : audiences[0]?.summary,
        firstFlagCreated: flags.map((flag) => flag.created_at).sort()[0] ?? null,
    }
    const released = isReleased(base)
    return { ...base, released, finished: released || base.ended }
}

function releaseStage(facts: ReleaseFacts): ReleaseStage {
    const { ended, released, running, paused, drafts, done, openEarlyAccess, flags } = facts
    if (ended) {
        return 'ended'
    }
    if (released) {
        return 'released'
    }
    if (running.length || paused.length || drafts.length || done.length) {
        return 'experiment'
    }
    if (openEarlyAccess) {
        return 'early_access'
    }
    return flags.length || facts.hasHiddenFlags || facts.pendingFlags ? 'flag' : 'planned'
}

function lastDoneCopy(lastDone: ExperimentBasicApi): { headline: string; detail: string } {
    return {
        headline: lastDone.end_date
            ? `Experiment ended on ${dayjs(lastDone.end_date).format(DAY_FORMAT)}`
            : 'Experiment stopped',
        detail: lastDone.conclusion
            ? `${CONCLUSION_LABEL[lastDone.conclusion] ?? lastDone.conclusion}.${lastDone.conclusion_comment ? ` ${lastDone.conclusion_comment}` : ''}`
            : 'No result is recorded on the experiment yet.',
    }
}

function releaseCopy(facts: ReleaseFacts): { status: string; headline: string; detail: string } {
    const { ended, released, running, paused, drafts, lastDone, openEarlyAccess, flags } = facts
    const { runningDays, firstStart, audienceSummary } = facts
    if (ended) {
        return {
            status: 'Ended, flags archived',
            headline: 'Release ended',
            detail: 'The flags of this release are archived, so it no longer changes.',
        }
    }
    if (released) {
        return {
            status: 'Rolled out to all users',
            headline: 'Rolled out to all users',
            detail: 'Every flag of this release serves it to everyone.',
        }
    }
    if (running.length) {
        return {
            status: `Experiment running, day ${runningDays}`,
            headline: `Experiment running for ${runningDays} day${runningDays === 1 ? '' : 's'}`,
            detail: `Started on ${dayjs(firstStart).format(DAY_FORMAT)}. Results are worth reading after about two weeks.`,
        }
    }
    if (paused.length) {
        return {
            status: 'Experiment paused',
            headline: 'Experiment paused',
            detail: `${paused[0].name} is paused, so it collects no new data.`,
        }
    }
    if (drafts.length) {
        return {
            status: 'Experiment in draft',
            headline: 'Experiment ready to launch',
            detail: `${drafts[0].name} is in draft. Nobody is in it yet.`,
        }
    }
    if (lastDone) {
        return { status: 'Experiment complete', ...lastDoneCopy(lastDone) }
    }
    if (openEarlyAccess) {
        return {
            status: `Early access, ${openEarlyAccess.stage}`,
            headline: `In early access, ${openEarlyAccess.stage}`,
            detail: 'Users can opt in to it before everyone gets it.',
        }
    }
    if (flags.length) {
        return {
            status: 'Behind a flag',
            headline: audienceSummary
                ? `${audienceSummary.charAt(0).toUpperCase()}${audienceSummary.slice(1)}`
                : 'Behind a flag',
            detail: '',
        }
    }
    if (facts.pendingFlags) {
        return { status: 'Loading flags…', headline: 'Loading flags…', detail: '' }
    }
    if (facts.hasHiddenFlags) {
        return {
            status: 'Flags hidden from you',
            headline: 'Behind flags you cannot see',
            detail: 'You do not have access to the flags of this release.',
        }
    }
    return {
        status: 'No feature flag yet',
        headline: 'Not started',
        detail: 'Link the feature flag that controls who gets this release.',
    }
}

function experimentNextStep(facts: ReleaseFacts): ReleaseNextStep | null {
    const { drafts, running, paused, current, runningDays, firstStart, lastDone, finished } = facts
    if (drafts.length && !running.length) {
        return {
            title: 'Launch the experiment',
            detail: `${drafts[0].name} is ready. Launch it to start collecting results.`,
            label: 'Open experiment',
            to: urls.experiment(drafts[0].id),
            urgent: true,
        }
    }
    if (current && runningDays >= REVIEW_AFTER_DAYS - 2) {
        return {
            title: 'Review the results',
            detail: `${current.name} has ${runningDays} days of data. Decide if the test variant should ship.`,
            label: 'Open results',
            to: urls.experiment(current.id),
            urgent: true,
        }
    }
    if (current) {
        return {
            title: 'Let the experiment run',
            detail: `Check the results around ${dayjs(firstStart).add(REVIEW_AFTER_DAYS, 'day').format(DAY_FORMAT)}, when it has two weeks of data.`,
            secondaryLabel: 'Open experiment',
            secondaryTo: urls.experiment(current.id),
        }
    }
    if (paused.length) {
        return {
            title: 'Resume or end the experiment',
            detail: `${paused[0].name} is paused. Resume it to collect more data, or end it and record the result.`,
            label: 'Open experiment',
            to: urls.experiment(paused[0].id),
            urgent: true,
        }
    }
    if (lastDone && !finished && !lastDone.conclusion) {
        return {
            title: 'Record the result',
            detail: `${lastDone.name} ended without a recorded result. Record it so the team knows what to ship.`,
            label: 'Open experiment',
            to: urls.experiment(lastDone.id),
            urgent: true,
        }
    }
    return null
}

function rolloutNextStep(facts: ReleaseFacts): ReleaseNextStep | null {
    const { flags, finished, prelaunchEarlyAccess, openEarlyAccess, lastDone, released } = facts
    if (!finished && prelaunchEarlyAccess) {
        return {
            title: EARLY_ACCESS_NEXT[prelaunchEarlyAccess.stage],
            detail: `${prelaunchEarlyAccess.name} is in ${prelaunchEarlyAccess.stage}, so nobody can opt in yet.`,
            label: 'Open early access',
            to: urls.earlyAccessFeature(prelaunchEarlyAccess.id),
        }
    }
    const widen = finished || openEarlyAccess ? undefined : flags.find(canWidenRollout)
    if (widen) {
        return {
            title: lastDone ? 'Roll out the winner' : 'Roll out to more users',
            detail: lastDone
                ? `Not everyone gets the winning variant yet. Roll ${widen.key} out to all users now or on a date.`
                : `Not everyone gets it yet. Widen the release conditions of ${widen.key}, or schedule a rollout to everyone.`,
            label: 'Schedule rollout',
            scheduleFlagId: widen.id,
            secondaryLabel: 'Open flag',
            secondaryTo: urls.featureFlag(widen.id),
            urgent: !!lastDone,
        }
    }
    if (openEarlyAccess && EARLY_ACCESS_NEXT[openEarlyAccess.stage]) {
        return {
            title: EARLY_ACCESS_NEXT[openEarlyAccess.stage],
            detail: `${openEarlyAccess.name} is in ${openEarlyAccess.stage}. Move it on when the feedback is good.`,
            label: 'Open early access',
            to: urls.earlyAccessFeature(openEarlyAccess.id),
        }
    }
    if (released) {
        return {
            title: 'Clean up the flag',
            detail: 'Everyone gets the release now. Remove the flag check from your code, then archive the flag.',
            label: 'Open flag',
            to: urls.featureFlag(flags[0].id),
        }
    }
    return null
}

function releaseNextStep(facts: ReleaseFacts): ReleaseNextStep | null {
    if (facts.pendingFlags && !facts.flags.length) {
        return null
    }
    if (!facts.flags.length && !facts.hasHiddenFlags) {
        return {
            title: 'Link a feature flag',
            detail: 'Pick the flag your code checks for this change, or create one.',
        }
    }
    if (!facts.complete) {
        return null
    }
    return experimentNextStep(facts) ?? rolloutNextStep(facts)
}

function releaseLifecycle(release: ReleaseDTOApi, facts: ReleaseFacts, stage: ReleaseStage): ReleaseLifecycleStep[] {
    const { experiments, earlyAccess, firstFlagCreated, ended, finished } = facts
    const testingStarts = [
        ...experiments
            .filter((experiment) => experiment.start_date)
            .map((experiment) => ({ date: experiment.start_date as string, label: 'Experiment' })),
        ...earlyAccess.map((item) => ({ date: item.created_at, label: 'Early access' })),
    ].sort((a, b) => a.date.localeCompare(b.date))
    const stageIndex = { planned: 0, flag: 1, experiment: 2, early_access: 2, released: 3, ended: 3 }[stage]
    return [
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
        { key: 'released' as const, label: ended ? 'Ended' : 'Rolled out', date: null },
    ].map((step, index) => ({
        ...step,
        date: index <= stageIndex ? step.date : null,
        state:
            index < stageIndex || (finished && index === stageIndex)
                ? 'done'
                : index === stageIndex
                  ? 'current'
                  : 'upcoming',
    }))
}

function experimentEvents(experiment: ExperimentBasicApi): ReleaseEvent[] {
    const href = urls.experiment(experiment.id)
    const events: ReleaseEvent[] = [
        {
            key: `exp-start-${experiment.id}`,
            date: experiment.start_date ?? experiment.created_at,
            kind: 'experiment',
            title: `${experiment.start_date ? 'Experiment launched' : 'Experiment drafted'}: ${experiment.name}`,
            href,
        },
    ]
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
    return events
}

function releaseEvents(release: ReleaseDTOApi, facts: ReleaseFacts, index: ReleaseIndex): ReleaseEvent[] {
    const { flags, earlyAccess, experiments } = facts
    return [
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
            title: `${isEnrollingEarlyAccess(item) || item.stage === 'general-availability' ? 'Early access opened' : 'Early access created'}: ${item.name}`,
            detail: `Now in ${item.stage}`,
            href: urls.earlyAccessFeature(item.id),
        })),
        ...experiments.flatMap(experimentEvents),
        ...release.broadcast_ids.flatMap((id) => index.sendEventsByBroadcastId.get(id) ?? []),
        ...flags.flatMap((flag) => index.scheduleEventsByFlagId.get(flag.id) ?? []),
    ]
}

function releaseSuggestions(facts: ReleaseFacts, stage: ReleaseStage): ReleaseSuggestion[] {
    const { complete, flags, experiments, earlyAccess, finished, broadcasts } = facts
    if (!complete || !flags.length) {
        return []
    }
    const suggestions: ReleaseSuggestion[] = []
    if (!broadcasts.length) {
        suggestions.push({
            key: 'broadcast',
            title: 'Tell users about it',
            detail: 'Send a broadcast when the release reaches more users. It links to this release on its own.',
            label: 'New broadcast',
            to: urls.broadcastNew(),
        })
    }
    if (finished) {
        return suggestions
    }
    if (!experiments.length) {
        suggestions.push({
            key: 'experiment',
            title: 'Measure the impact',
            detail: 'Run an experiment on this flag to see if the release helps.',
            label: 'New experiment',
            to: urls.experiment('new'),
        })
    }
    if (!earlyAccess.length && stage === 'flag') {
        suggestions.push({
            key: 'early-access',
            title: 'Let users opt in first',
            detail: 'Interested users try the release before everyone gets it.',
            label: 'New early access feature',
            to: urls.earlyAccessFeature('new'),
        })
    }
    return suggestions
}

function experimentSpan(experiment: ExperimentBasicApi, today: dayjs.Dayjs, end: string): ReleaseSpan {
    const from = (experiment.start_date as string).slice(0, 10)
    const finished = isExperimentDone(experiment)
    return {
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
    }
}

function flagLook(facts: ReleaseFacts): Pick<ReleaseSpan, 'label' | 'tone' | 'href'> {
    const { flags, audiences, released, ended } = facts
    const more = flags.length > 1 ? ` +${flags.length - 1}` : ''
    const href = urls.featureFlag(flags[0].id)
    if (ended) {
        return { label: `Archived${more}`, tone: 'default', href }
    }
    if (released) {
        return { label: `Everyone${more}`, tone: 'success', href }
    }
    if (!flags[0].active) {
        return { label: `${flags[0].key} off${more}`, tone: 'default', href }
    }
    const percent = audiences[0]?.percent
    return {
        label: `${flags[0].key} ${percent === null || percent === undefined ? '' : `${percent}%`}${more}`.trim(),
        tone: 'default',
        href,
    }
}

function releaseSpans(facts: ReleaseFacts): ReleaseSpan[] {
    const { today, firstFlagCreated, earlyAccess, running, paused, done } = facts
    const end = today.format('YYYY-MM-DD')
    const spans: ReleaseSpan[] = []
    const opened = earlyAccess.filter((entry) => !['draft', 'concept', 'archived'].includes(entry.stage))
    if (firstFlagCreated) {
        const from = firstFlagCreated.slice(0, 10)
        const earlyAccessFrom = opened.map((item) => item.created_at.slice(0, 10)).sort()[0]
        const to =
            earlyAccessFrom && earlyAccessFrom > from
                ? dayjs(earlyAccessFrom).subtract(1, 'day').format('YYYY-MM-DD')
                : end
        if (!earlyAccessFrom || earlyAccessFrom > from) {
            spans.push({ ...flagLook(facts), key: 'flag', kind: 'flag', from, to })
        }
    }
    for (const item of opened) {
        spans.push({
            key: `ea-${item.id}`,
            kind: 'early_access',
            label:
                item.stage === 'general-availability'
                    ? 'Early access, general availability'
                    : `Early access, ${item.stage}`,
            from: item.created_at.slice(0, 10),
            to: end,
            href: urls.earlyAccessFeature(item.id),
        })
    }
    for (const experiment of [...running, ...paused, ...done]) {
        if (experiment.start_date) {
            spans.push(experimentSpan(experiment, today, end))
        }
    }
    return spans
}

function releaseAudience(facts: ReleaseFacts): string {
    if (facts.openEarlyAccess) {
        return 'Users who opt in'
    }
    if (facts.running.length) {
        return 'Experiment participants'
    }
    return facts.audienceSummary || 'Nobody yet'
}

export function buildReleaseRow(release: ReleaseDTOApi, index: ReleaseIndex): ReleaseRow {
    const facts = releaseFacts(release, index)
    const stage = releaseStage(facts)
    const nextStep = releaseNextStep(facts)
    const events = releaseEvents(release, facts, index)
    return {
        id: release.id,
        name: release.name,
        description: release.description,
        createdAt: release.created_at,
        owner: release.owner,
        missingFlagIds: facts.missingFlagIds,
        ...releaseCopy(facts),
        lifecycle: releaseLifecycle(release, facts, stage),
        audiences: facts.audiences,
        events,
        suggestions: releaseSuggestions(facts, stage).map((suggestion) =>
            suggestion.key === 'broadcast'
                ? {
                      ...suggestion,
                      to: combineUrl(urls.broadcastNew(), {
                          [NAME_PREFILL_PARAM]: release.name,
                          [SOURCE_PREFILL_PARAM]: 'release',
                          [SOURCE_RECORD_PREFILL_PARAM]: releaseSourceRecord(release.id),
                      }).url,
                  }
                : suggestion
        ),
        flags: facts.flags,
        experiments: facts.experiments,
        earlyAccess: facts.earlyAccess,
        broadcasts: facts.broadcasts,
        stage,
        audience: releaseAudience(facts),
        nextStep,
        needsDecision: (!facts.flags.length && !facts.hasHiddenFlags) || !!nextStep?.urgent,
        runningDays: facts.runningDays,
        nextDate:
            events
                .filter((event) => event.upcoming)
                .map((event) => event.date)
                .sort()[0] ?? null,
        spans: releaseSpans(facts),
    }
}

export type LinkKind = 'flag' | 'broadcast'

export interface LinkCandidate {
    key: string
    kind: LinkKind
    id: string
    label: string
}

const STOP_WORDS = new Set(['the', 'and', 'for', 'with', 'new', 'release', 'test', 'beta', 'launch', 'flag'])

export function nameTokens(name: string): string[] {
    return [
        ...new Set(
            name
                .toLowerCase()
                .split(/[^a-z0-9]+/)
                .filter((token) => token.length >= 3 && !STOP_WORDS.has(token))
        ),
    ]
}

export function rankLinkSuggestions(releaseName: string, candidates: LinkCandidate[], limit = 5): LinkCandidate[] {
    const wanted = new Set(nameTokens(releaseName))
    if (!wanted.size) {
        return []
    }
    return candidates
        .map((candidate) => ({
            candidate,
            score: nameTokens(candidate.label).filter((token) => wanted.has(token)).length,
        }))
        .filter(({ score }) => score > 0)
        .sort((a, b) => b.score - a.score || a.candidate.label.localeCompare(b.candidate.label))
        .slice(0, limit)
        .map(({ candidate }) => candidate)
}
