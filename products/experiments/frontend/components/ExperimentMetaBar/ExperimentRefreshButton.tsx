import { useActions, useAsyncActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, lemonToast } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { experimentLogic, previousRefreshAnalytics } from 'scenes/experiments/experimentLogic'
import { experimentMetricsLogic } from 'scenes/experiments/experimentMetricsLogic'

import { Experiment } from '~/types'

import { ExperimentLastRefreshText } from './ExperimentLastRefreshText'

interface RefreshButtonProps {
    isRefreshing: boolean
    lastRefresh: string | null
    progress?: { completed: number; total: number }
    queuedHint?: string
    blockedReason?: string
    onRefresh: () => void
}

function RefreshButton({
    isRefreshing,
    lastRefresh,
    progress,
    queuedHint,
    blockedReason,
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
            disabledReason={isRefreshing ? (queuedHint ?? loadingText) : blockedReason}
            aria-label={isRefreshing ? undefined : 'Refresh results'}
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

export function ExperimentRefreshButton({ experiment }: { experiment: Experiment }): JSX.Element {
    const metricsLogic = experimentMetricsLogic({ experiment })
    const {
        isRecalculating,
        recalculationProgress,
        lastRefresh,
        queuedRerun,
        isManualRefreshBlocked,
        nextAllowedManualRefresh,
        backendEnforcesRefreshWindow,
    } = useValues(metricsLogic)
    const { triggerRecalculation } = useActions(metricsLogic)
    const { currentRefresh } = useValues(experimentLogic)
    const { reportExperimentMetricsRefreshed } = useActions(experimentLogic)
    const { refreshExperimentResults } = useAsyncActions(experimentLogic)
    // A page with stale flags learns about the window from a 429, so the backend signal counts too.
    const showRefreshWindow = useFeatureFlag('EXPERIMENTS_RECALCULATION_RATE_LIMIT') || backendEnforcesRefreshWindow

    return (
        <RefreshButton
            isRefreshing={isRecalculating}
            lastRefresh={lastRefresh}
            progress={recalculationProgress}
            queuedHint={queuedRerun ? 'Changes apply after the current recalculation finishes' : undefined}
            blockedReason={
                showRefreshWindow && isManualRefreshBlocked && nextAllowedManualRefresh
                    ? `Next refresh possible ${dayjs(nextAllowedManualRefresh).fromNow()}`
                    : undefined
            }
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
