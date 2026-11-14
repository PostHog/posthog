import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import type { FeatureFlagApi } from 'products/feature_flags/frontend/generated/api.schemas'

import type { RelatedInsight, RelatedSurvey } from './releaseRelated'
import { RolloutStep } from './releaseRollout'
import {
    CALENDAR_DAYS_AFTER,
    CALENDAR_DAYS_BEFORE,
    ReleaseEvent,
    ReleaseFlagAudience,
    ReleaseRow,
    ReleaseSpan,
    STAGE_COLOR,
} from './releaseUtils'

export const DAY = 30
export const TOTAL = CALENDAR_DAYS_BEFORE + CALENDAR_DAYS_AFTER
export const LANE = 34
export const DETAILED_LANE = 44
const NO_STEPS: RolloutStep[] = []

export const SPAN_LOOK: Record<ReleaseSpan['kind'], { top: number; height: number; color: string }> = {
    flag: { top: 30, height: 14, color: STAGE_COLOR.flag },
    early_access: { top: 4, height: 14, color: STAGE_COLOR.early_access },
    experiment: { top: 4, height: 14, color: STAGE_COLOR.experiment },
    experiment_done: { top: 4, height: 14, color: STAGE_COLOR.ended },
    survey: { top: 4, height: 14, color: 'var(--release-survey)' },
}

export const TONE_COLOR: Record<NonNullable<ReleaseSpan['tone']>, string> = {
    default: STAGE_COLOR.ended,
    info: STAGE_COLOR.experiment,
    warning: STAGE_COLOR.early_access,
    success: STAGE_COLOR.released,
}

export interface Scale {
    start: dayjs.Dayjs
    days: number
    day: number
}

export const CALENDAR_SCALE = (): Scale => ({
    start: dayjs().startOf('day').subtract(CALENDAR_DAYS_BEFORE, 'day'),
    days: TOTAL,
    day: DAY,
})

export function x(date: string, scale: Scale): number {
    return Math.max(0, Math.min(scale.days, dayjs(date).startOf('day').diff(scale.start, 'day'))) * scale.day
}

const LAST_STEP_MIN_WIDTH = 108
const MIN_SEGMENT_WIDTH = 4

export interface RolloutSegment {
    step: RolloutStep
    left: number
    width: number
    projected: boolean
}

export function rolloutSegments(steps: RolloutStep[], scale: Scale, today: dayjs.Dayjs): RolloutSegment[] {
    const end = scale.days * scale.day
    const windowEnd = scale.start.add(scale.days, 'day')
    const todayX = x(today.toISOString(), scale) + scale.day / 2
    const past = steps.filter((step) => !step.upcoming)
    const upcoming = steps.filter((step) => step.upcoming)
    const current = past[past.length - 1]
    const raw = [
        ...past.map((step) => ({
            step,
            from: step.from,
            to: step === current ? today.toISOString() : step.to,
            left: x(step.from, scale),
            right: step === current ? todayX : x(step.to, scale),
            projected: false,
        })),
        ...(current && upcoming.length
            ? [
                  {
                      step: current,
                      from: today.toISOString(),
                      to: upcoming[0].from,
                      left: todayX,
                      right: x(upcoming[0].from, scale),
                      projected: true,
                  },
              ]
            : []),
        ...upcoming.map((step, index) => {
            const left = x(step.from, scale)
            const next = upcoming[index + 1]
            return {
                step,
                from: step.from,
                to: next ? next.from : step.to,
                left,
                right: next ? x(next.from, scale) : Math.min(left + Math.max(3 * scale.day, LAST_STEP_MIN_WIDTH), end),
                projected: false,
            }
        }),
    ]
    return raw
        .filter(({ from, to }) => dayjs(from).isBefore(windowEnd) && !dayjs(to).isBefore(scale.start, 'day'))
        .map(({ step, left, right, projected }) => ({
            step,
            left,
            width: Math.max(right - left, MIN_SEGMENT_WIDTH),
            projected,
        }))
}

const PAST_SHARE = 0.65

export function todayScrollLeft(
    scale: Scale,
    viewportWidth: number,
    stickyWidth: number,
    today: dayjs.Dayjs
): number | null {
    const visible = viewportWidth - stickyWidth
    const todayX = x(today.toISOString(), scale) + scale.day / 2
    return todayX > visible - scale.day ? Math.max(0, todayX - visible * PAST_SHARE) : null
}

export function linkedKeys(row: ReleaseRow, related: TrackRelated | undefined): Set<string> {
    return new Set([
        ...row.flags.map((flag) => `flag:${flag.id}`),
        ...row.broadcasts.map((broadcast) => `broadcast:${broadcast.id}`),
        ...(related?.surveys ?? []).map((survey) => `survey:${survey.id}`),
        ...(related?.insights ?? []).map((insight) => `insight:${insight.id}`),
    ])
}

export type Lane =
    | {
          key: string
          kind: 'flag'
          title: string
          status: string
          live: boolean
          steps: RolloutStep[]
          events: ReleaseEvent[]
          span: ReleaseSpan
          href: string
          flag: FeatureFlagApi
          audience?: ReleaseFlagAudience
      }
    | {
          key: string
          kind: 'experiment' | 'early_access'
          title: string
          status: string
          live: boolean
          span: ReleaseSpan | null
          href: string
      }
    | {
          key: string
          kind: 'broadcast'
          title: string
          status: string
          live: boolean
          events: ReleaseEvent[]
          href: string
      }
    | {
          key: string
          kind: 'survey'
          title: string
          status: string
          live: boolean
          span: ReleaseSpan
          href: string
      }

export interface Track {
    row: ReleaseRow
    steps: RolloutStep[]
    lanes: Lane[]
}

export interface TrackRelated {
    surveys: RelatedSurvey[]
    insights: RelatedInsight[]
}

const NO_RELATED: TrackRelated = { surveys: [], insights: [] }

export function relatedFor(
    release: { survey_ids?: string[]; insight_ids?: number[] } | undefined,
    surveysById: Record<string, RelatedSurvey>,
    insightsById: Record<number, RelatedInsight>
): TrackRelated {
    if (!release) {
        return NO_RELATED
    }
    return {
        surveys: (release.survey_ids ?? []).flatMap((id) => (surveysById[id] ? [surveysById[id]] : [])),
        insights: (release.insight_ids ?? []).flatMap((id) => (insightsById[id] ? [insightsById[id]] : [])),
    }
}

export function surveyStatus(survey: RelatedSurvey): 'Archived' | 'Complete' | 'Running' | 'Draft' {
    return survey.archived ? 'Archived' : survey.endDate ? 'Complete' : survey.startDate ? 'Running' : 'Draft'
}

export function buildTrack(
    row: ReleaseRow,
    stepsByFlag: Map<number, RolloutStep[]>,
    related: TrackRelated = NO_RELATED
): Track {
    const lanes: Lane[] = []
    for (const flag of row.flags) {
        lanes.push({
            key: `flag-${flag.id}`,
            kind: 'flag',
            title: flag.key,
            status: flag.active ? 'Live' : 'Off',
            live: !!flag.active,
            steps: stepsByFlag.get(flag.id) ?? NO_STEPS,
            events: row.events.filter(
                (event) => event.kind === 'schedule' && event.upcoming && event.flagId === flag.id
            ),
            span: {
                key: `flag-span-${flag.id}`,
                kind: 'flag',
                from: flag.created_at,
                to: dayjs().toISOString(),
                label: flag.active ? 'Live' : 'Off',
                tone: flag.active ? undefined : 'default',
                href: urls.featureFlag(flag.id),
            },
            href: urls.featureFlag(flag.id),
            flag,
            audience: row.audiences.find((audience) => audience.flag.id === flag.id),
        })
    }
    for (const experiment of row.experiments) {
        const span = row.spans.find((item) => item.href === urls.experiment(experiment.id)) ?? null
        lanes.push({
            key: `experiment-${experiment.id}`,
            kind: 'experiment',
            title: experiment.name,
            status: experiment.end_date ? 'Complete' : experiment.start_date ? 'Running' : 'Draft',
            live: !!experiment.start_date && !experiment.end_date,
            span,
            href: urls.experiment(experiment.id),
        })
    }
    for (const item of row.earlyAccess) {
        lanes.push({
            key: `early-access-${item.id}`,
            kind: 'early_access',
            title: item.name,
            status: item.stage,
            live: ['alpha', 'beta', 'general-availability'].includes(item.stage),
            span: row.spans.find((span) => span.key === `ea-${item.id}`) ?? null,
            href: urls.earlyAccessFeature(item.id),
        })
    }
    for (const broadcast of row.broadcasts) {
        lanes.push({
            key: `broadcast-${broadcast.id}`,
            kind: 'broadcast',
            title: broadcast.name || 'Untitled broadcast',
            status: broadcast.status,
            live: broadcast.status === 'active',
            events: row.events.filter(
                (event) => event.kind === 'broadcast' && event.href === urls.broadcast(broadcast.id)
            ),
            href: urls.broadcast(broadcast.id),
        })
    }
    for (const survey of related.surveys) {
        const status = surveyStatus(survey)
        lanes.push({
            key: `survey-${survey.id}`,
            kind: 'survey',
            title: survey.name,
            status,
            live: status === 'Running',
            span: {
                key: `survey-span-${survey.id}`,
                kind: 'survey',
                from: survey.startDate ?? survey.createdAt,
                to:
                    survey.endDate ??
                    (status === 'Archived' ? (survey.startDate ?? survey.createdAt) : dayjs().toISOString()),
                label:
                    status === 'Draft'
                        ? 'Survey draft'
                        : status === 'Running'
                          ? 'Survey running'
                          : status === 'Archived'
                            ? 'Survey archived'
                            : 'Survey',
                href: urls.survey(survey.id),
            },
            href: urls.survey(survey.id),
        })
    }
    return { row, steps: row.flags[0] ? (stepsByFlag.get(row.flags[0].id) ?? NO_STEPS) : NO_STEPS, lanes }
}

export function sendLabel(event: ReleaseEvent): string {
    const kind = event.title.split(':')[0].replace('Broadcast', '').trim()
    return event.upcoming ? 'Scheduled' : kind ? kind[0].toUpperCase() + kind.slice(1) : 'Sent'
}

export function laneHeight(detailed?: boolean): number {
    return detailed ? DETAILED_LANE : LANE
}

export function statusLabel(status: string): string {
    return status.charAt(0).toUpperCase() + status.slice(1).replace('-', ' ')
}

export function mergeOverlapping(spans: ReleaseSpan[]): ReleaseSpan[] {
    const merged: (ReleaseSpan & { count: number })[] = []
    const family = (kind: ReleaseSpan['kind']): string => (kind.startsWith('experiment') ? 'experiment' : kind)
    for (const span of [...spans].sort((a, b) => a.from.localeCompare(b.from))) {
        const previous = merged.find(
            (item) => family(item.kind) === family(span.kind) && !dayjs(span.from).isAfter(dayjs(item.to), 'day')
        )
        if (!previous) {
            merged.push({ ...span, count: 1 })
            continue
        }
        previous.count += 1
        previous.to = dayjs(span.to).isAfter(dayjs(previous.to)) ? span.to : previous.to
        if (span.kind === 'experiment') {
            previous.kind = 'experiment'
            previous.tone = span.tone
        }
        previous.label = span.kind.startsWith('experiment')
            ? `${previous.count} experiments`
            : `${previous.label?.split(' +')[0] ?? ''} +${previous.count - 1}`
    }
    return merged
}
