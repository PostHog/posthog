import { useActions, useValues } from 'kea'
import { ComponentType, ReactNode } from 'react'

import * as chartPng from '@posthog/brand/hoggies/png/chart'
import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import * as mailboxPng from '@posthog/brand/hoggies/png/mailbox'
import * as megaphonePng from '@posthog/brand/hoggies/png/megaphone'
import { LemonSkeleton, Link } from '@posthog/lemon-ui'

import { HoggiePngProps, pngHoggie } from 'lib/brand/hoggies'
import { BannerAction } from 'lib/components/BannerDeck/BannerActionButton'
import { BannerDeck } from 'lib/components/BannerDeck/BannerDeck'
import { urls } from 'scenes/urls'

import { FixWithAgentButton } from '../components/FixWithAgentButton'
import { formatNumber } from '../dashboard/formatters'
import { METRICS_UNLOCK_LIFETIME_CALLS, mcpAnalyticsOnboardingLogic } from '../mcpAnalyticsOnboardingLogic'
import { ActivityCard } from './ActivityCard'
import { ActivityCardKey, activityCardsLogic } from './activityCardsLogic'
import { mcpEarlyDataLogic } from './mcpEarlyDataLogic'
import type { NextStep } from './nextSteps'

const CARD_HOGS: Record<ActivityCardKey, ComponentType<HoggiePngProps>> = {
    welcome: pngHoggie(chartPng),
    'weekly-report': pngHoggie(mailboxPng),
    notification: pngHoggie(megaphonePng),
    intent: pngHoggie(magnifyingGlassPng),
}

export function ActivityCards(): JSX.Element | null {
    const { cards, currentCard } = useValues(activityCardsLogic)
    const { dismissCard, showPreviousCard, showNextCard } = useActions(activityCardsLogic)
    const { nextSteps, summary, overview, overviewLoading } = useValues(mcpEarlyDataLogic)
    const { showFailedCallsOnly, nextStepClicked } = useActions(mcpEarlyDataLogic)
    const { dashboardStage } = useValues(mcpAnalyticsOnboardingLogic)

    if (!currentCard) {
        return null
    }

    const stepActions = (
        step: NextStep
    ): { primary?: BannerAction; primaryControl?: ReactNode; secondary?: BannerAction } => {
        const dataAttr = `mcp-analytics-activity-next-step-${step.key}`
        if (step.action.kind === 'link') {
            return {
                primary: {
                    label: step.action.label,
                    to: step.action.to,
                    onClick: () => nextStepClicked(step.key, 'open'),
                    dataAttr,
                },
            }
        }
        if (step.action.kind === 'agent-prompt') {
            return {
                primaryControl: (
                    <FixWithAgentButton
                        fix={step.action.fix}
                        dataAttr={dataAttr}
                        onRun={() => nextStepClicked(step.key, 'open')}
                    />
                ),
                secondary: {
                    label: 'Docs',
                    to: step.action.fix.docsUrl,
                    targetBlank: true,
                    onClick: () => nextStepClicked(step.key, 'docs'),
                    dataAttr: `${dataAttr}-docs`,
                },
            }
        }
        return {}
    }

    // Keyed by card, so each one mounts fresh as the stack moves.
    const renderCard = (card: ActivityCardKey, navigation?: ReactNode): ReactNode => {
        const shared = { illustration: CARD_HOGS[card], navigation, onDismiss: () => dismissCard(card) }
        if (card === 'welcome') {
            return (
                <ActivityCard
                    key={card}
                    {...shared}
                    title={
                        // An absent overview reads as zero calls, so the first load waits for the numbers.
                        overviewLoading && !overview ? (
                            <LemonSkeleton className="h-5 w-80 max-w-full" />
                        ) : (
                            <span>{summary.headline}</span>
                        )
                    }
                    description={
                        <>
                            Each tool call shows up in the feed below as agents use your server.
                            {dashboardStage === 'activity' ? (
                                <>
                                    {' '}
                                    Charts and trends live in the{' '}
                                    <Link to={urls.mcpAnalyticsDashboard()}>Dashboard tab</Link> once usage grows (~
                                    {formatNumber(METRICS_UNLOCK_LIFETIME_CALLS)} calls).
                                </>
                            ) : null}
                        </>
                    }
                    primaryAction={
                        summary.failures
                            ? {
                                  label: `Show ${summary.failures}`,
                                  onClick: showFailedCallsOnly,
                                  dataAttr: 'mcp-analytics-activity-failures-link',
                              }
                            : undefined
                    }
                />
            )
        }
        const step = nextSteps?.find((nextStep) => nextStep.key === card)
        if (!step) {
            return null
        }
        const { primary, primaryControl, secondary } = stepActions(step)
        return (
            <ActivityCard
                key={card}
                {...shared}
                title={step.title}
                description={step.detail}
                primaryAction={primary}
                primaryControl={primaryControl}
                secondaryAction={secondary}
            />
        )
    }

    return (
        <BannerDeck
            banners={cards}
            current={currentCard}
            onPrevious={showPreviousCard}
            onNext={showNextCard}
            renderCurrent={(navigation) => renderCard(currentCard, navigation)}
            dataAttrPrefix="mcp-analytics-activity-cards"
        />
    )
}
