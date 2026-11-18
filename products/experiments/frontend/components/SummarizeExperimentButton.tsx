import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { addProductIntent } from 'lib/utils/product-intents'
import { experimentLogic, getSectionMetricUuids } from 'scenes/experiments/experimentLogic'
import { useMaxTool } from 'scenes/max/useMaxTool'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { EXPERIMENT_MIN_EXPOSURES_FOR_RESULTS } from 'products/experiments/frontend/constants'
import { isLaunched } from 'products/experiments/frontend/experimentStatus'
import { getTotalExposures } from 'products/experiments/frontend/health/exposureHealth'
import { useAttachedContext } from 'products/posthog_ai/frontend/api/logics'

/**
 * Minimal context sent to the backend for experiment summarization.
 * The backend fetches all detailed experiment data using the experiment_id.
 * This has the benefit that the AI can be called from other places too.
 */
interface MinimalExperimentSummaryContext {
    experiment_id: number | string
    experiment_name: string
}

function useExperimentSummaryMaxTool(): ReturnType<typeof useMaxTool> {
    const { experiment } = useValues(experimentLogic)

    // Simplified context - backend will fetch full data using experiment_id
    const maxToolContext = useMemo(
        (): MinimalExperimentSummaryContext => ({
            experiment_id: experiment.id,
            experiment_name: experiment.name || 'Unnamed experiment',
        }),
        [experiment.id, experiment.name]
    )

    const shouldShowMaxSummaryTool = useMemo(() => {
        const hasPrimaryMetrics = getSectionMetricUuids(experiment, false).length > 0
        const hasStarted = isLaunched(experiment)
        return hasPrimaryMetrics && hasStarted
    }, [experiment])

    const maxToolResult = useMaxTool({
        identifier: 'experiment_results_summary',
        context: maxToolContext,
        contextDescription: {
            text: maxToolContext.experiment_name,
            icon: iconForType('experiment'),
        },
        active: shouldShowMaxSummaryTool,
        initialMaxPrompt: `!Summarize the experiment "${experiment.name}"`,
        callback(toolOutput) {
            addProductIntent({
                product_type: ProductKey.EXPERIMENTS,
                intent_context: ProductIntentContext.EXPERIMENT_ANALYZED,
                metadata: {
                    experiment_id: experiment.id,
                },
            })

            if (toolOutput?.error) {
                posthog.captureException(toolOutput?.error || 'Undefined error when summarizing experiment with Max', {
                    action: 'max-ai-experiment-summary-failed',
                    experiment_id: experiment.id,
                    ...toolOutput,
                })
            }
        },
    })

    useAttachedContext(
        shouldShowMaxSummaryTool
            ? [{ type: 'experiment', key: experiment.id, label: experiment.name || 'Unnamed experiment' }]
            : null
    )

    return maxToolResult
}

export function SummarizeExperimentButton({ iconOnly = false }: { iconOnly?: boolean }): JSX.Element | null {
    const { openMax } = useExperimentSummaryMaxTool()
    const { experiment, hasMinimumExposureForResults, exposures } = useValues(experimentLogic)
    const { reportExperimentAiSummaryRequested } = useActions(experimentLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const resultsRedesign = useFeatureFlag('EXPERIMENTS_RESULTS_REDESIGN')
    if (!openMax) {
        return null
    }

    const summarize = (): void => {
        reportExperimentAiSummaryRequested(experiment)
        openMax()
    }

    if (iconOnly) {
        return (
            <Tooltip title="Summarize results with PostHog AI" placement="top-end" delayMs={0}>
                <button
                    type="button"
                    aria-label="Summarize results with PostHog AI"
                    data-attr="experiment-summarize-results"
                    className="size-6 shrink-0 cursor-pointer rounded-md border border-dashed border-ai bg-ai/08 backdrop-blur-[2px] transition duration-50 hover:scale-110 dark:bg-ai/20"
                    onClick={summarize}
                >
                    <IconSparkles className="relative size-full p-1 text-ai dark:text-white" />
                </button>
            </Tooltip>
        )
    }

    const totalExposures = getTotalExposures(exposures)
    const disabledReason = hasMinimumExposureForResults
        ? undefined
        : `Summaries need at least ${EXPERIMENT_MIN_EXPOSURES_FOR_RESULTS} exposures. This experiment has ${totalExposures}.`

    if (todayRailNav && resultsRedesign) {
        return (
            <Button
                variant="outline"
                data-attr="experiment-summarize-results"
                disabledReason={disabledReason}
                onClick={summarize}
            >
                <IconSparkles />
                Summarize with PostHog AI
            </Button>
        )
    }

    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconSparkles className="text-ai" />}
            data-attr="experiment-summarize-results"
            disabledReason={disabledReason}
            onClick={summarize}
        >
            Summarize with PostHog AI
        </LemonButton>
    )
}
