import { useValues } from 'kea'
import { ReactNode } from 'react'

import { Badge, Skeleton, Text, cn } from '@posthog/quill'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { LaneInsights, errorRate, errorsLookWorse, leadingOutcome } from './releaseLaneInsights'
import { LaneUsage, UsageTarget } from './releaseLaneUsage'
import { releaseLaneUsageLogic } from './releaseLaneUsageLogic'

function percent(value: number): string {
    return `${Math.round(value * 1000) / 10}%`
}

function share(usage: LaneUsage, label: string): number {
    return usage.split.find((item) => item.label === label)?.users ?? 0
}

function Headline({ value, label, className }: { value: string; label: ReactNode; className?: string }): JSX.Element {
    return (
        <div className="flex min-w-0 items-baseline gap-1.5">
            <Text size="lg" weight="semibold" className={cn('shrink-0 tabular-nums', className)}>
                {value}
            </Text>
            <Text size="xs" variant="muted" className="min-w-0 truncate">
                {label}
            </Text>
        </div>
    )
}

function Line({ children, title }: { children: ReactNode; title?: string }): JSX.Element {
    return (
        <Text size="xs" variant="muted" className="truncate" title={title}>
            {children}
        </Text>
    )
}

function Warning({ children, title }: { children: ReactNode; title?: string }): JSX.Element {
    return (
        <Text size="xs" variant="destructive" className="truncate" title={title} data-attr="release-inspector-warning">
            {children}
        </Text>
    )
}

function ErrorWarning({ insights }: { insights: LaneInsights | null }): JSX.Element | null {
    const errors = insights?.kind === 'flag' || insights?.kind === 'experiment' ? insights.errors : []
    const worse = errorsLookWorse(errors)
    const baseline = errors.find((item) => item.label === 'Without it' || item.label === 'control')
    if (!worse || !baseline) {
        return null
    }
    return (
        <Warning>
            {`More errors ${worse.label === 'With the feature' ? 'with the feature' : `in ${worse.label}`}: ${percent(errorRate(worse))} vs ${percent(errorRate(baseline))}`}
        </Warning>
    )
}

function FlagSummary({ usage, insights }: { usage: LaneUsage; insights: LaneInsights | null }): JSX.Element {
    const total = usage.split.reduce((sum, item) => sum + item.users, 0)
    const got = share(usage, 'Got the feature')
    const health = insights?.kind === 'flag' ? insights.health : null
    return (
        <>
            <Headline
                value={humanFriendlyNumber(usage.weekUsers)}
                label={
                    total ? `users this week, ${Math.round((got / total) * 100)}% got the feature` : 'users this week'
                }
            />
            <ErrorWarning insights={insights} />
            {health && !['active', 'unknown'].includes(health.status) && (
                <Warning title={health.reason}>{health.reason}</Warning>
            )}
        </>
    )
}

function ExperimentSummary({ insights }: { insights: LaneInsights | null }): JSX.Element {
    const experiment = insights?.kind === 'experiment' ? insights : null
    const lead = experiment ? leadingOutcome(experiment.outcomes) : null
    if (!experiment?.metricName) {
        return <Line>Add a primary metric to see which variant wins.</Line>
    }
    if (!lead || lead.change === null) {
        return <Line title={experiment.metricName}>{`${experiment.metricName}: not enough data yet`}</Line>
    }
    const good = experiment.goal === 'decrease' ? lead.change < 0 : lead.change > 0
    return (
        <>
            <div className="flex min-w-0 items-center gap-2" data-attr="release-inspector-result">
                <Headline
                    value={`${lead.change > 0 ? '+' : ''}${percent(lead.change)}`}
                    className={good ? 'text-success-foreground' : 'text-destructive-foreground'}
                    label={lead.key}
                />
                <Badge variant={lead.significant ? (good ? 'success' : 'destructive') : 'default'} className="shrink-0">
                    {lead.significant
                        ? good
                            ? 'Winning'
                            : 'Losing'
                        : lead.chanceToWin !== null
                          ? `${Math.round(lead.chanceToWin * 100)}% chance to win`
                          : 'No winner yet'}
                </Badge>
            </div>
            <Line title={experiment.metricName}>{experiment.metricName}</Line>
            <ErrorWarning insights={insights} />
            {experiment.findings[0] && (
                <Warning title={experiment.findings.join('\n')}>{experiment.findings[0]}</Warning>
            )}
        </>
    )
}

function SurveySummary({ usage, insights }: { usage: LaneUsage; insights: LaneInsights | null }): JSX.Element {
    const survey = insights?.kind === 'survey' ? insights : null
    const shown = share(usage, 'Shown')
    const answered = share(usage, 'Answered')
    const latest = survey?.latest[0]
    return (
        <>
            <Headline
                value={shown ? `${Math.round((answered / shown) * 100)}%` : humanFriendlyNumber(answered)}
                label={
                    survey?.rating
                        ? `answered, rated ${Math.round(survey.rating.average * 10) / 10} of ${survey.rating.scale}`
                        : shown
                          ? 'answered'
                          : 'answers'
                }
            />
            {latest && (
                <Text size="xs" className="truncate italic" title={latest} data-attr="release-inspector-answer">
                    {`“${latest}”`}
                </Text>
            )}
        </>
    )
}

function EarlyAccessSummary({ usage, insights }: { usage: LaneUsage; insights: LaneInsights | null }): JSX.Element {
    const optedIn = insights?.kind === 'early_access' ? insights.optedIn : null
    const net = share(usage, 'Opted in') - share(usage, 'Opted out')
    return (
        <Headline
            value={optedIn === null ? '–' : humanFriendlyNumber(optedIn)}
            label={`opted in, ${net >= 0 ? '+' : ''}${humanFriendlyNumber(net)} this week`}
        />
    )
}

export function ReleaseLaneSummary({ target, from }: { target: UsageTarget; from: string }): JSX.Element {
    const { usage, usageLoading, insights } = useValues(releaseLaneUsageLogic({ target, from }))
    if (usageLoading && !usage) {
        return <Skeleton className="h-10 w-full" />
    }
    if (!usage) {
        return (
            <Text size="xs" variant="muted">
                Usage could not load.
            </Text>
        )
    }
    return (
        <div className="flex flex-col gap-1" data-attr="release-inspector-summary">
            {target.kind === 'flag' ? (
                <FlagSummary usage={usage} insights={insights} />
            ) : target.kind === 'experiment' ? (
                <ExperimentSummary insights={insights} />
            ) : target.kind === 'survey' ? (
                <SurveySummary usage={usage} insights={insights} />
            ) : (
                <EarlyAccessSummary usage={usage} insights={insights} />
            )}
        </div>
    )
}
