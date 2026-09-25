import { useActions, useAsyncActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, lemonToast } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { experimentLogic, previousRefreshAnalytics } from 'scenes/experiments/experimentLogic'
import { experimentMetricsLogic } from 'scenes/experiments/experimentMetricsLogic'

import { Experiment } from '~/types'

import { ExperimentLastRefreshText } from './ExperimentLastRefreshText'

interface RefreshButtonProps {
    isRefreshing: boolean
    lastRefresh: string | null
    progress?: { completed: number; total: number }
    queuedHint?: string
    onRefresh: () => void
}

function RefreshButton({
    isRefreshing,
    lastRefresh,
    progress,
    queuedHint,
    onRefresh,
}: RefreshButtonProps): JSX.Element {
    const loadingText =
        progress && progress.total > 0 ? `Loading ${progress.completed} of ${progress.total} metrics…` : 'Loading…'

    return (
        <LemonButton
            type="secondary"
            size="xsmall"
            icon={isRefreshing ? <Spinner textColored /> : <IconRefresh />}
            onClick={onRefresh}
            disabledReason={isRefreshing ? (queuedHint ?? loadingText) : undefined}
            tooltip={isRefreshing ? undefined : 'Refresh results'}
            data-attr="refresh-experiment"
        >
            {isRefreshing ? (
                <span>{loadingText}</span>
            ) : (
                <span className="flex items-center gap-1">
                    <span className="text-secondary">Refreshed</span>
                    <ExperimentLastRefreshText lastRefresh={lastRefresh} />
                </span>
            )}
        </LemonButton>
    )
}

function RecalculationRefreshButton({ experiment }: { experiment: Experiment }): JSX.Element {
    const metricsLogic = experimentMetricsLogic({ experiment })
    const { isRecalculating, recalculationProgress, lastRefresh, queuedRerun } = useValues(metricsLogic)
    const { triggerRecalculation } = useActions(metricsLogic)
    const { currentRefresh } = useValues(experimentLogic)
    const { reportExperimentMetricsRefreshed } = useActions(experimentLogic)
    const { refreshExperimentResults } = useAsyncActions(experimentLogic)

    return (
        <RefreshButton
            isRefreshing={isRecalculating}
            lastRefresh={lastRefresh}
            progress={recalculationProgress}
            queuedHint={queuedRerun ? 'Changes apply after the current recalculation finishes' : undefined}
            onRefresh={() => {
                reportExperimentMetricsRefreshed(experiment, true, {
                    triggered_by: 'manual',
                    ...previousRefreshAnalytics(currentRefresh),
                })
                triggerRecalculation()
                // Exposures still live in experimentLogic, so refresh them alongside the recalculation.
                void refreshExperimentResults(true, 'manual').catch(() => {
                    lemonToast.error('Could not refresh results. Try again.')
                })
            }}
        />
    )
}

function LegacyRefreshButton({ experiment }: { experiment: Experiment }): JSX.Element {
    const {
        primaryMetricsResults,
        secondaryMetricsResults,
        primaryMetricsResultsLoading,
        secondaryMetricsResultsLoading,
        exposuresLoading,
        currentRefresh,
    } = useValues(experimentLogic)
    const { reportExperimentMetricsRefreshed } = useActions(experimentLogic)
    const { refreshExperimentResults } = useAsyncActions(experimentLogic)

    const lastRefresh = primaryMetricsResults?.[0]?.last_refresh || secondaryMetricsResults?.[0]?.last_refresh || null

    return (
        <RefreshButton
            isRefreshing={primaryMetricsResultsLoading || secondaryMetricsResultsLoading || exposuresLoading}
            lastRefresh={lastRefresh}
            onRefresh={() => {
                reportExperimentMetricsRefreshed(experiment, true, {
                    triggered_by: 'manual',
                    ...previousRefreshAnalytics(currentRefresh),
                })
                void refreshExperimentResults(true, 'manual').catch(() => {
                    lemonToast.error('Could not refresh results. Try again.')
                })
            }}
        />
    )
}

export function ExperimentRefreshButton({ experiment }: { experiment: Experiment }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    return featureFlags[FEATURE_FLAGS.EXPERIMENTS_METRICS_RECALCULATION] ? (
        <RecalculationRefreshButton experiment={experiment} />
    ) : (
        <LegacyRefreshButton experiment={experiment} />
    )
}
