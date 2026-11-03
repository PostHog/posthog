import { useActions, useValues } from 'kea'
import type { ComponentType, ReactNode } from 'react'

import * as lifeguardPng from '@posthog/brand/hoggies/png/lifeguard'
import * as mailboxPng from '@posthog/brand/hoggies/png/mailbox'
import { IconArrowRight, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonCard, Spinner } from '@posthog/lemon-ui'

import { type HoggiePngProps, pngHoggie } from 'lib/brand/hoggies'
import { urls } from 'scenes/urls'

import { mcpEarlyDataLogic } from '../earlyData/mcpEarlyDataLogic'
import { WeeklyReportActions } from '../earlyData/WeeklyReportActions'
import { SetupCallsPanel } from './SetupCallsPanel'
import { SetupStepHero } from './SetupStepHero'
import { SetupStepLayout } from './SetupStepLayout'

const HedgehogMailbox = pngHoggie(mailboxPng)
const HedgehogLifeguard = pngHoggie(lifeguardPng)

const COPY = {
    title: 'Hear from your server without opening PostHog',
    lead: 'Pick one or both. You can change them later in Notifications.',
    report: {
        // Shown while the report offer resolves, and when this project can't get the one-click report.
        title: 'Get a weekly report',
        detail: 'Volume, error rate and latency per tool, delivered where you choose.',
        hasReport: 'Your project already has a weekly report. Change it or add another in Notifications.',
        open: 'Open notifications',
    },
    alert: {
        title: 'Get alerted when a tool call fails',
        detail: 'Send new failures to Slack, Discord, Microsoft Teams, or a webhook.',
        detailAfterFailure: (tool: string) =>
            `A call to ${tool} failed. Send the next failure to Slack, Discord, Microsoft Teams, or a webhook.`,
        set: 'Set up an alert',
        alreadySet: 'You already get an alert when a tool call fails.',
        manage: 'Manage alerts',
    },
    expect: {
        title: 'What to expect',
        detail: 'Every tool call shows up here live from now on. Trends, tool quality and intent clusters fill in once your server has a few hundred calls.',
    },
    askAI: 'Ask PostHog AI what you can do',
    // Sent to PostHog AI as the first message. A question about the product rather than the data, because
    // a server this new has only a few calls to analyze.
    aiPrompt: 'What can MCP analytics tell me about my MCP server, and what should I look at as tool calls come in?',
    finish: 'Open MCP analytics',
}

function OptionCard({
    Hedgehog,
    title,
    detail,
    error,
    actions,
}: {
    Hedgehog: ComponentType<Pick<HoggiePngProps, 'className'>>
    title: string
    detail: string
    error?: string
    actions: ReactNode
}): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-4 p-5">
            <Hedgehog className="h-20 w-auto self-start" />
            <div className="flex flex-1 flex-col gap-1">
                <h3 className="m-0 text-base font-semibold">{title}</h3>
                <p className="m-0 text-sm text-secondary">{detail}</p>
                {error ? (
                    <p className="m-0 text-sm text-danger" role="alert">
                        {error}
                    </p>
                ) : null}
            </div>
            <div className="flex flex-wrap items-center gap-1">{actions}</div>
        </LemonCard>
    )
}

function WeeklyReportOption(): JSX.Element {
    const { nextSteps, weeklyReportOffer } = useValues(mcpEarlyDataLogic)
    const { nextStepClicked } = useActions(mcpEarlyDataLogic)
    const reportStep = nextSteps?.find((step) => step.key === 'weekly-report')

    if (reportStep?.action.kind === 'weekly-report') {
        return (
            <OptionCard
                Hedgehog={HedgehogMailbox}
                title={reportStep.title}
                detail={reportStep.detail}
                error={reportStep.error}
                actions={<WeeklyReportActions offer={reportStep.action.offer} />}
            />
        )
    }
    if (nextSteps === null) {
        return (
            <OptionCard
                Hedgehog={HedgehogMailbox}
                title={COPY.report.title}
                detail={COPY.report.detail}
                actions={<Spinner />}
            />
        )
    }
    const hasReport = weeklyReportOffer.state === 'hidden' && weeklyReportOffer.reason === 'has-report'
    return (
        <OptionCard
            Hedgehog={HedgehogMailbox}
            title={COPY.report.title}
            detail={hasReport ? COPY.report.hasReport : COPY.report.detail}
            actions={
                <LemonButton
                    type="secondary"
                    size="small"
                    to={urls.mcpAnalyticsNotifications()}
                    onClick={() => nextStepClicked('weekly-report', 'more-options')}
                    data-attr="mcp-analytics-activity-next-step-weekly-report-options"
                >
                    {COPY.report.open}
                </LemonButton>
            }
        />
    )
}

function FailureAlertOption(): JSX.Element {
    const { overview, hasFailureNotification } = useValues(mcpEarlyDataLogic)
    const { nextStepClicked } = useActions(mcpEarlyDataLogic)
    const failedTool = overview?.recent_calls.find((call) => call.is_error)?.tool
    return (
        <OptionCard
            Hedgehog={HedgehogLifeguard}
            title={COPY.alert.title}
            detail={
                hasFailureNotification
                    ? COPY.alert.alreadySet
                    : failedTool
                      ? COPY.alert.detailAfterFailure(failedTool)
                      : COPY.alert.detail
            }
            actions={
                <LemonButton
                    type="secondary"
                    size="small"
                    to={urls.mcpAnalyticsNotifications()}
                    onClick={() => nextStepClicked('notification', 'open')}
                    data-attr="mcp-analytics-activity-next-step-notification"
                >
                    {hasFailureNotification ? COPY.alert.manage : COPY.alert.set}
                </LemonButton>
            }
        />
    )
}

export function SetupUsefulStep({
    onFinish,
    onAskPostHogAI,
}: {
    onFinish: () => void
    onAskPostHogAI: (prompt: string) => void
}): JSX.Element {
    const { overview } = useValues(mcpEarlyDataLogic)
    return (
        <SetupStepLayout aside={<SetupCallsPanel calls={overview?.recent_calls ?? null} />}>
            <SetupStepHero title={COPY.title} lead={COPY.lead} />
            <div className="@container">
                <div className="grid gap-4 @min-[34rem]:grid-cols-2">
                    <WeeklyReportOption />
                    <FailureAlertOption />
                </div>
            </div>
            <div className="flex flex-col gap-1">
                <h3 className="m-0 text-sm font-semibold">{COPY.expect.title}</h3>
                <p className="m-0 text-sm text-secondary">{COPY.expect.detail}</p>
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2">
                <LemonButton
                    type="secondary"
                    size="large"
                    sideIcon={<IconArrowRight />}
                    onClick={onFinish}
                    data-attr="mcp-analytics-setup-mode-finish"
                >
                    {COPY.finish}
                </LemonButton>
                <LemonButton
                    type="primary"
                    size="large"
                    icon={<IconSparkles />}
                    onClick={() => onAskPostHogAI(COPY.aiPrompt)}
                    data-attr="mcp-analytics-setup-mode-ask-ai"
                >
                    {COPY.askAI}
                </LemonButton>
            </div>
        </SetupStepLayout>
    )
}
