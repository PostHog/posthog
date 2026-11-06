import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconArrowRight, IconBell, IconLetter, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonCard, Spinner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { mcpEarlyDataLogic } from '../earlyData/mcpEarlyDataLogic'
import { weeklyReportStep } from '../earlyData/nextSteps'
import { WeeklyReportActions } from '../earlyData/WeeklyReportActions'
import type { MCPActivityRecentCallApi } from '../generated/api.schemas'
import { SetupStepHero } from './SetupStepHero'
import { SetupStepLayout } from './SetupStepLayout'

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
    icon,
    title,
    detail,
    error,
    actions,
}: {
    icon: ReactNode
    title: string
    detail: string
    error?: string
    actions: ReactNode
}): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-4 p-5">
            <span className="flex size-10 items-center justify-center rounded border border-primary bg-surface-secondary text-xl">
                {icon}
            </span>
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

// Reads the offer itself rather than the activity next steps, which also wait on the overview request.
function WeeklyReportOption(): JSX.Element {
    const { weeklyReportOffer } = useValues(mcpEarlyDataLogic)
    const { nextStepClicked } = useActions(mcpEarlyDataLogic)

    if (weeklyReportOffer.state === 'loading') {
        return (
            <OptionCard
                icon={<IconLetter />}
                title={COPY.report.title}
                detail={COPY.report.detail}
                actions={<Spinner />}
            />
        )
    }
    if (weeklyReportOffer.state !== 'hidden') {
        const reportStep = weeklyReportStep(weeklyReportOffer)
        return (
            <OptionCard
                icon={<IconLetter />}
                title={reportStep.title}
                detail={reportStep.detail}
                error={reportStep.error}
                actions={<WeeklyReportActions offer={weeklyReportOffer} />}
            />
        )
    }
    const hasReport = weeklyReportOffer.reason === 'has-report'
    return (
        <OptionCard
            icon={<IconLetter />}
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

function FailureAlertOption({ calls }: { calls: readonly MCPActivityRecentCallApi[] | null }): JSX.Element {
    const { hasFailureNotification } = useValues(mcpEarlyDataLogic)
    const { nextStepClicked } = useActions(mcpEarlyDataLogic)
    const failedTool = calls?.find((call) => call.is_error)?.tool
    return (
        <OptionCard
            icon={<IconBell />}
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
    calls,
    onFinish,
    onAskPostHogAI,
}: {
    calls: readonly MCPActivityRecentCallApi[] | null
    onFinish: () => void
    onAskPostHogAI: (prompt: string) => void
}): JSX.Element {
    return (
        <SetupStepLayout>
            <SetupStepHero title={COPY.title} lead={COPY.lead} />
            <div className="@container">
                <div className="grid gap-4 @min-[34rem]:grid-cols-2">
                    <WeeklyReportOption />
                    <FailureAlertOption calls={calls} />
                </div>
            </div>
            <div className="flex flex-col gap-1">
                <h3 className="m-0 text-sm font-semibold">{COPY.expect.title}</h3>
                <p className="m-0 text-sm text-secondary">{COPY.expect.detail}</p>
            </div>
            {/* The weekly report is this step's one primary action, so the way out stays secondary. */}
            <div className="flex flex-wrap items-center justify-end gap-2">
                <LemonButton
                    type="secondary"
                    icon={<IconSparkles />}
                    onClick={() => onAskPostHogAI(COPY.aiPrompt)}
                    data-attr="mcp-analytics-setup-mode-ask-ai"
                >
                    {COPY.askAI}
                </LemonButton>
                <LemonButton
                    type="secondary"
                    sideIcon={<IconArrowRight />}
                    onClick={onFinish}
                    data-attr="mcp-analytics-setup-mode-finish"
                >
                    {COPY.finish}
                </LemonButton>
            </div>
        </SetupStepLayout>
    )
}
