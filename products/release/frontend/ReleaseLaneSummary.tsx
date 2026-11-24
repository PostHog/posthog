import { useValues } from 'kea'
import { ReactNode } from 'react'

import { Badge, Skeleton, Text, cn } from '@posthog/quill'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { ErrorSplit, LaneInsights, errorRate, errorsLookWorse, leadingOutcome } from './releaseLaneInsights'
import { LaneUsage, UsageTarget } from './releaseLaneUsage'
import { releaseLaneUsageLogic } from './releaseLaneUsageLogic'

function percent(value: number): string {
    return `${Math.round(value * 1000) / 10}%`
}

function signed(value: number): string {
    return `${value > 0 ? '+' : ''}${percent(value)}`
}

function share(usage: LaneUsage | null, label: string): number {
    return usage?.split.find((item) => item.label === label)?.users ?? 0
}

function Headline({ value, label, className }: { value: string; label: ReactNode; className?: string }): JSX.Element {
    return (
        <div className="flex items-baseline gap-1.5">
            <Text size="lg" weight="semibold" className={cn('shrink-0 tabular-nums', className)}>
                {value}
            </Text>
            <Text size="xs" variant="muted" className="min-w-0">
                {label}
            </Text>
        </div>
    )
}

function Line({ children, title, dataAttr }: { children: ReactNode; title?: string; dataAttr?: string }): JSX.Element {
    return (
        <Text size="xs" variant="muted" className="truncate" title={title} data-attr={dataAttr}>
            {children}
        </Text>
    )
}

function Split({ usage, percentages }: { usage: LaneUsage; percentages: boolean }): JSX.Element | null {
    const total = usage.split.reduce((sum, item) => sum + item.users, 0)
    if (!usage.split.length || !total) {
        return null
    }
    return (
        <Line dataAttr="release-lane-detail-split">
            {usage.split.map((item, index) => (
                <span key={item.label}>
                    {index > 0 && <span>{' · '}</span>}
                    <span className="text-foreground">{item.label}</span>
                    <span className="tabular-nums">
                        {` ${percentages ? `${Math.round((item.users / total) * 100)}%` : humanFriendlyNumber(item.users)}`}
                    </span>
                </span>
            ))}
        </Line>
    )
}

function Errors({ errors }: { errors: ErrorSplit[] }): JSX.Element | null {
    if (!errors.length || errors.every((item) => item.errored === 0)) {
        return null
    }
    const worse = errorsLookWorse(errors)
    return (
        <Line dataAttr="release-lane-detail-errors">
            <span>{'Errors '}</span>
            {errors.slice(0, 3).map((item, index) => (
                <span key={item.label}>
                    {index > 0 && <span>{' · '}</span>}
                    <span
                        className={cn(
                            'tabular-nums',
                            item === worse ? 'font-medium text-destructive-foreground' : 'text-foreground'
                        )}
                    >
                        {percent(errorRate(item))}
                    </span>
                    <span>{` ${item.label.charAt(0).toLowerCase()}${item.label.slice(1)}`}</span>
                </span>
            ))}
        </Line>
    )
}

function FlagSummary({ usage, insights }: { usage: LaneUsage; insights: LaneInsights | null }): JSX.Element {
    const flag = insights?.kind === 'flag' ? insights : null
    const stale = flag?.health && !['active', 'unknown'].includes(flag.health.status) ? flag.health : null
    return (
        <>
            <Headline
                value={humanFriendlyNumber(usage.weekUsers)}
                label="users had this flag checked in the last 7 days"
            />
            <Split usage={usage} percentages />
            {flag && <Errors errors={flag.errors} />}
            {stale && (
                <Line title={stale.reason} dataAttr="release-lane-detail-health">
                    <Badge variant="warning" className="mr-1.5">
                        {stale.status.charAt(0).toUpperCase() + stale.status.slice(1)}
                    </Badge>
                    <span>{stale.reason}</span>
                </Line>
            )}
        </>
    )
}

function ExperimentSummary({ usage, insights }: { usage: LaneUsage; insights: LaneInsights | null }): JSX.Element {
    const experiment = insights?.kind === 'experiment' ? insights : null
    const lead = experiment ? leadingOutcome(experiment.outcomes) : null
    const good = lead?.change != null && (experiment?.goal === 'decrease' ? lead.change < 0 : lead.change > 0)
    return (
        <>
            {!experiment?.metricName ? (
                <Line>No primary metric. Add one to the experiment to see which variant wins.</Line>
            ) : !lead || lead.change === null ? (
                <>
                    <Line>{experiment.metricName}</Line>
                    <Line>Not enough data to compare the variants yet.</Line>
                </>
            ) : (
                <div className="flex flex-col gap-0.5" data-attr="release-lane-detail-result">
                    <div className="flex min-w-0 items-center gap-2">
                        <Text size="xs" variant="muted" className="min-w-0 truncate" title={experiment.metricName}>
                            {experiment.metricName}
                        </Text>
                        <Badge variant={lead.significant ? (good ? 'success' : 'destructive') : 'default'}>
                            {lead.significant
                                ? `${lead.key} ${good ? 'wins' : 'loses'}`
                                : lead.chanceToWin !== null
                                  ? `${Math.round(lead.chanceToWin * 100)}% chance to win`
                                  : 'No winner yet'}
                        </Badge>
                    </div>
                    <Headline
                        value={signed(lead.change)}
                        className={good ? 'text-success-foreground' : 'text-destructive-foreground'}
                        label={`${lead.key} vs control`}
                    />
                </div>
            )}
            <Line>
                <span className="text-foreground tabular-nums">{humanFriendlyNumber(usage.weekUsers)}</span>
                <span>{' users in the last 7 days'}</span>
            </Line>
            {experiment && <Errors errors={experiment.errors} />}
            {experiment?.findings[0] && (
                <Line title={experiment.findings.join('\n')} dataAttr="release-lane-detail-health">
                    <Badge variant="warning" className="mr-1.5">
                        Check
                    </Badge>
                    <span>{experiment.findings[0]}</span>
                </Line>
            )}
        </>
    )
}

function SurveySummary({ usage, insights }: { usage: LaneUsage; insights: LaneInsights | null }): JSX.Element {
    const survey = insights?.kind === 'survey' ? insights : null
    const shown = share(usage, 'Shown')
    const answered = share(usage, 'Answered')
    return (
        <>
            <Headline
                value={shown ? percent(answered / shown) : humanFriendlyNumber(answered)}
                label={shown ? `answered (${answered} of ${shown} who saw it)` : 'answers'}
            />
            {survey?.rating && (
                <Line title={survey.rating.question} dataAttr="release-lane-detail-rating">
                    <span>{'Average rating '}</span>
                    <span className="font-medium text-foreground tabular-nums">
                        {`${Math.round(survey.rating.average * 10) / 10} of ${survey.rating.scale}`}
                    </span>
                    <span>{` · ${survey.rating.answers} ${survey.rating.answers === 1 ? 'rating' : 'ratings'}`}</span>
                </Line>
            )}
            {survey?.latest.slice(0, 2).map((answer, index) => (
                <Text
                    key={index}
                    size="xs"
                    className="truncate italic"
                    title={answer}
                    data-attr="release-lane-detail-answer"
                >
                    {`“${answer}”`}
                </Text>
            ))}
        </>
    )
}

function EarlyAccessSummary({ usage, insights }: { usage: LaneUsage; insights: LaneInsights | null }): JSX.Element {
    const optedIn = insights?.kind === 'early_access' ? insights.optedIn : null
    const net = share(usage, 'Opted in') - share(usage, 'Opted out')
    return (
        <>
            <Headline value={optedIn === null ? '–' : humanFriendlyNumber(optedIn)} label="users opted in now" />
            <Line>
                <span className={cn('tabular-nums', net > 0 ? 'text-success-foreground' : 'text-foreground')}>
                    {`${net > 0 ? '+' : ''}${humanFriendlyNumber(net)}`}
                </span>
                <span>{' this week'}</span>
                <span>{` · ${share(usage, 'Opted in')} opted in, ${share(usage, 'Opted out')} opted out`}</span>
            </Line>
        </>
    )
}

export function ReleaseLaneSummary({ target, from }: { target: UsageTarget; from: string }): JSX.Element {
    const { usage, usageLoading, insights } = useValues(releaseLaneUsageLogic({ target, from }))
    if (usageLoading && !usage) {
        return <Skeleton className="h-12 w-full" />
    }
    if (!usage) {
        return (
            <Text size="xs" variant="muted">
                Usage could not load.
            </Text>
        )
    }
    return (
        <div className="flex flex-col gap-1" data-attr="release-lane-detail-summary">
            {target.kind === 'flag' ? (
                <FlagSummary usage={usage} insights={insights} />
            ) : target.kind === 'experiment' ? (
                <ExperimentSummary usage={usage} insights={insights} />
            ) : target.kind === 'survey' ? (
                <SurveySummary usage={usage} insights={insights} />
            ) : (
                <EarlyAccessSummary usage={usage} insights={insights} />
            )}
        </div>
    )
}
