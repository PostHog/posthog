import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import * as greekPng from '@posthog/brand/hoggies/png/greek'
import { LemonButton, Link, Spinner } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { useInterval } from 'lib/hooks/useInterval'
import { teamLogic } from 'scenes/teamLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { metricsIngestionLogic } from '../metricsIngestionLogic'

const HedgehogGreek = pngHoggie(greekPng)

const POLLING_INTERVAL_MS = 5000

export const MetricsSetupPrompt = ({
    children,
    className,
}: {
    children: React.ReactNode
    className?: string
}): JSX.Element => {
    const { hasMetrics, teamHasMetricsLoading, teamHasMetricsCheckFailed } = useValues(metricsIngestionLogic)
    const { currentTeam } = useValues(teamLogic)

    if ((teamHasMetricsLoading && hasMetrics === undefined) || !currentTeam) {
        return (
            <div className="flex justify-center">
                <Spinner />
            </div>
        )
    }

    if (teamHasMetricsCheckFailed || hasMetrics === undefined) {
        return <>{children}</>
    }

    if (!hasMetrics) {
        return <NoMetricsPrompt className={className} />
    }

    return <>{children}</>
}

const NoMetricsPrompt = ({ className }: { className?: string }): JSX.Element | null => {
    const { addProductIntent } = useActions(teamLogic)
    const { hasMetrics } = useValues(metricsIngestionLogic)
    const { loadTeamHasMetrics } = useActions(metricsIngestionLogic)

    useEffect(() => {
        posthog.capture('metrics setup prompt viewed')
    }, [])

    useInterval(() => {
        if (!hasMetrics) {
            loadTeamHasMetrics()
        }
    }, POLLING_INTERVAL_MS)

    const onDocsLinkClick = (docsType: string): void => {
        posthog.capture('metrics onboarding docs clicked', { docs_type: docsType })
        addProductIntent({
            product_type: ProductKey.METRICS,
            intent_context: ProductIntentContext.METRICS_DOCS_VIEWED,
        })
    }

    return (
        <ProductIntroduction
            productName="Metrics"
            thingName="metric"
            titleOverride="You haven't sent any metrics yet"
            description="PostHog metrics works with any OpenTelemetry-compatible client. You don't need any PostHog-specific packages – just use standard OpenTelemetry libraries to send metrics via OTLP."
            isEmpty={true}
            productKey={ProductKey.METRICS}
            className={className}
            customHog={HedgehogGreek}
            actionElementOverride={
                <div className="flex flex-col items-start gap-4">
                    <p className="text-sm text-secondary m-0">
                        Read our{' '}
                        <Link to="https://posthog.com/docs/metrics" onClick={() => onDocsLinkClick('Metrics')}>
                            metrics docs
                        </Link>{' '}
                        or learn more about{' '}
                        <Link
                            to="https://opentelemetry.io/docs/what-is-opentelemetry/"
                            target="_blank"
                            disableDocsPanel
                            onClick={() => onDocsLinkClick('OpenTelemetry')}
                        >
                            OpenTelemetry
                        </Link>
                        .
                    </p>
                    <div className="flex items-center gap-4">
                        <div className="flex items-center gap-2 px-3 py-1.5 border border-accent rounded">
                            <div className="relative flex items-center justify-center">
                                <div className="absolute w-3 h-3 border-2 border-accent rounded-full animate-ping" />
                                <div className="w-2 h-2 bg-accent rounded-full" />
                            </div>
                            <span className="text-sm">Watching for metrics</span>
                        </div>
                        <LemonButton
                            type="secondary"
                            size="small"
                            to="https://posthog.com/docs/metrics"
                            onClick={() => onDocsLinkClick('Docs')}
                        >
                            View docs
                        </LemonButton>
                    </div>
                </div>
            }
        />
    )
}
