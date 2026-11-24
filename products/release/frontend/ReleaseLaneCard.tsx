import { Text } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { RelatedSurvey } from './releaseRelated'
import { RolloutStep } from './releaseRollout'
import { Lane, statusLabel } from './releaseTracks'
import { REVIEW_AFTER_DAYS, ReleaseSpan } from './releaseUtils'

export const LANE_CARD_CLASS =
    'w-60 max-w-none items-stretch rounded-md border border-border bg-card p-3 text-foreground shadow-[var(--shadow-md)] [&>*:last-child]:hidden'

const KIND_ICON: Record<Lane['kind'] | ReleaseSpan['kind'], string> = {
    flag: 'feature_flag',
    experiment: 'experiment',
    experiment_done: 'experiment',
    early_access: 'early_access_feature',
    broadcast: 'broadcasts',
    survey: 'survey',
}

export type Fact = [label: string, value: string]

function day(date: string): string {
    return dayjs(date).format('D MMM')
}

function days(count: number): string {
    return `${count} ${count === 1 ? 'day' : 'days'}`
}

function ongoing(to: string): boolean {
    return !dayjs(to).isBefore(dayjs(), 'day')
}

function between(from: string, to?: string): number {
    return (to ? dayjs(to) : dayjs()).startOf('day').diff(dayjs(from).startOf('day'), 'day')
}

function started(from: string): Fact {
    const count = between(from)
    return ['Started', `${day(from)}, ${count ? `${days(count)} ago` : 'today'}`]
}

function ended(from: string, to: string): Fact {
    return ['Ended', `${day(to)}, after ${days(Math.max(1, between(from, to)))}`]
}

function starts(from: string): Fact {
    const count = between(dayjs().toISOString(), from)
    return ['Starts', `${day(from)}, ${count ? `in ${days(count)}` : 'today'}`]
}

function percent(step: RolloutStep): string {
    return step.label === 'Everyone' ? '100%' : step.label
}

function rolloutFacts(lane: Lane | undefined, step: RolloutStep, next: RolloutStep | undefined): Fact[] {
    if (step.upcoming) {
        return [['Planned', percent(step)], starts(step.from)]
    }
    const audience = lane?.kind === 'flag' && lane.flag.active && ongoing(step.to) ? lane.audience : undefined
    const who = audience?.percent != null ? audience.who.toLowerCase() : undefined
    return [
        ['Rollout', who ? `${percent(step)} of ${who}` : percent(step)],
        started(step.from),
        ongoing(step.to)
            ? ['Next', next ? `${percent(next)} on ${day(next.from)}` : 'Nothing scheduled']
            : ended(step.from, step.to),
    ]
}

function experimentFacts(span: ReleaseSpan): Fact[] {
    if (span.kind === 'experiment_done' || !ongoing(span.to)) {
        return [started(span.from), ended(span.from, span.to)]
    }
    if (span.label === 'Experiment paused') {
        return [['Progress', 'Paused'], started(span.from)]
    }
    const elapsed = between(span.from)
    return [
        ['Progress', `Day ${Math.min(elapsed + 1, REVIEW_AFTER_DAYS)} of ${REVIEW_AFTER_DAYS}`],
        started(span.from),
        [
            'Results',
            elapsed >= REVIEW_AFTER_DAYS
                ? 'Ready to read'
                : `Around ${day(dayjs(span.from).add(REVIEW_AFTER_DAYS, 'day').toISOString())}`,
        ],
    ]
}

function surveyFacts(survey: RelatedSurvey): Fact[] {
    if (!survey.startDate) {
        return [['Started', 'Not yet']]
    }
    if (survey.endDate) {
        return [started(survey.startDate), ended(survey.startDate, survey.endDate)]
    }
    return survey.archived ? [started(survey.startDate)] : [started(survey.startDate), ['Ends', 'No end date']]
}

function spanFacts(span: ReleaseSpan): Fact[] {
    return ongoing(span.to) ? [started(span.from)] : [started(span.from), ended(span.from, span.to)]
}

interface LaneCardProps {
    lane?: Lane
    step?: RolloutStep
    next?: RolloutStep
    span?: ReleaseSpan
}

export function laneCardFacts({ lane, step, next, span }: LaneCardProps): Fact[] {
    const facts = step
        ? rolloutFacts(lane, step, next)
        : lane?.kind === 'survey'
          ? surveyFacts(lane.survey)
          : span && (span.count ?? 1) === 1 && (span.kind === 'experiment' || span.kind === 'experiment_done')
            ? experimentFacts(span)
            : span
              ? spanFacts(span)
              : []
    return lane ? [['Status', statusLabel(lane.status)], ...facts] : facts
}

export function ReleaseLaneCard({ lane, step, next, span }: LaneCardProps): JSX.Element {
    const title = lane?.title ?? span?.label ?? ''
    const kind = lane?.kind ?? span?.kind ?? 'flag'
    const facts = laneCardFacts({ lane, step, next, span })
    return (
        <div className="flex w-full flex-col gap-1.5">
            <div className="flex min-w-0 items-start gap-2">
                <span className="flex size-4 shrink-0 items-center justify-center text-muted-foreground [&_svg]:mt-0 [&_svg]:block [&_svg]:size-3.5">
                    {iconForType(KIND_ICON[kind] as never)}
                </span>
                <Text size="xs" render={<span />} className="line-clamp-2 min-w-0 flex-1 break-words">
                    {title}
                </Text>
            </div>
            <div className="grid grid-cols-[3.5rem_minmax(0,1fr)] items-center gap-x-2 gap-y-1.5">
                {facts.map(([label, value]) => (
                    <div key={label} className="contents">
                        <Text size="xs" variant="muted" render={<span />} className="truncate">
                            {label}
                        </Text>
                        <Text size="xs" render={<span />} className="truncate" title={value}>
                            {value}
                        </Text>
                    </div>
                ))}
            </div>
        </div>
    )
}
