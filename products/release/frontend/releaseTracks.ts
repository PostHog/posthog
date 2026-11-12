import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { RolloutStep } from './releaseRollout'
import {
    CALENDAR_DAYS_AFTER,
    CALENDAR_DAYS_BEFORE,
    ReleaseEvent,
    ReleaseRow,
    ReleaseSpan,
    STAGE_COLOR,
} from './releaseUtils'

export const DAY = 30
export const TOTAL = CALENDAR_DAYS_BEFORE + CALENDAR_DAYS_AFTER
export const LANE = 34
export const FLAG_LANE = 52

export const SPAN_LOOK: Record<ReleaseSpan['kind'], { top: number; height: number; color: string }> = {
    flag: { top: 30, height: 14, color: STAGE_COLOR.flag },
    early_access: { top: 4, height: 14, color: STAGE_COLOR.early_access },
    experiment: { top: 4, height: 14, color: STAGE_COLOR.experiment },
    experiment_done: { top: 4, height: 14, color: STAGE_COLOR.ended },
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

export type Lane =
    | {
          key: string
          kind: 'flag'
          title: string
          status: string
          live: boolean
          steps: RolloutStep[]
          span: ReleaseSpan
          href: string
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

export interface Track {
    row: ReleaseRow
    steps: RolloutStep[]
    lanes: Lane[]
}

export function buildTrack(row: ReleaseRow, stepsByFlag: Map<number, RolloutStep[]>): Track {
    const lanes: Lane[] = []
    for (const flag of row.flags) {
        lanes.push({
            key: `flag-${flag.id}`,
            kind: 'flag',
            title: flag.key,
            status: flag.active ? 'Live' : 'Off',
            live: !!flag.active,
            steps: stepsByFlag.get(flag.id) ?? [],
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
    return { row, steps: row.flags[0] ? (stepsByFlag.get(row.flags[0].id) ?? []) : [], lanes }
}

export function sendLabel(event: ReleaseEvent): string {
    const kind = event.title.split(':')[0].replace('Broadcast', '').trim()
    return event.upcoming ? 'Scheduled' : kind ? kind[0].toUpperCase() + kind.slice(1) : 'Sent'
}

export function laneHeight(lane: Lane): number {
    return lane.kind === 'flag' ? FLAG_LANE : LANE
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
