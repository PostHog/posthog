import { useActions, useValues } from 'kea'
import React from 'react'

import { IconInfo, IconTestTube } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { percentage } from 'lib/utils/numbers'
import { getExperimentMetricFromInsight } from 'scenes/experiments/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { FunnelVizType, type InsightModel } from '~/types'

import { FunnelStepsPicker } from './filters/FunnelStepsPicker'
import { funnelDataLogic } from './funnelDataLogic'
import { QuillFunnelCanvasLabel } from './QuillFunnelCanvasLabel'

const EXPERIMENT_TOOLTIP = 'Create a draft experiment with the metric from this funnel.'

export function FunnelCanvasLabel(): JSX.Element | null {
    const { insightProps, insight, supportsCreatingExperiment, derivedName } = useValues(insightLogic)
    const { conversionMetrics, aggregationTargetLabel, funnelVizType, hasPartialBreakdownSelection } = useValues(
        funnelDataLogic(insightProps)
    )
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))
    const { addProductIntentForCrossSell } = useActions(teamLogic)
    const quillSurface = useQuillSurface()

    const totalRate = percentage(conversionMetrics.totalRate, 2, true)
    const totalRateTooltip = hasPartialBreakdownSelection
        ? `Overall conversion rate for ${aggregationTargetLabel.plural} in the selected breakdown values on the entire funnel.`
        : `Overall conversion rate for all ${aggregationTargetLabel.plural} on the entire funnel.`
    const medianTime = conversionMetrics.medianTime != null ? humanFriendlyDuration(conversionMetrics.medianTime) : null
    const medianTimeLabel = hasPartialBreakdownSelection
        ? 'Median time to convert (all breakdowns)'
        : 'Median time to convert'
    const medianTimeTooltip = `Median (50th percentile) of the total time each ${aggregationTargetLabel.singular} spent in the entire funnel.${hasPartialBreakdownSelection ? ' This median includes all breakdown values.' : ''}`
    const showTimeToConvert = (): void => updateInsightFilter({ funnelVizType: FunnelVizType.TimeToConvert })
    const experimentUrl = supportsCreatingExperiment
        ? urls.experiment('new', null, {
              metric: getExperimentMetricFromInsight(insight as InsightModel),
              name: insight.name || insight.derived_name || derivedName,
          })
        : null
    const trackExperimentIntent = (): void =>
        addProductIntentForCrossSell({
            from: ProductKey.PRODUCT_ANALYTICS,
            to: ProductKey.EXPERIMENTS,
            intent_context: ProductIntentContext.CREATE_EXPERIMENT_FROM_FUNNEL_BUTTON,
        })

    if (quillSurface) {
        return (
            <QuillFunnelCanvasLabel
                funnelVizType={funnelVizType}
                totalRate={totalRate}
                totalRateTooltip={totalRateTooltip}
                medianTime={medianTime}
                medianTimeLabel={medianTimeLabel}
                medianTimeTooltip={medianTimeTooltip}
                onShowTimeToConvert={showTimeToConvert}
                experimentUrl={experimentUrl}
                experimentTooltip={EXPERIMENT_TOOLTIP}
                onRunExperiment={trackExperimentIntent}
            />
        )
    }

    const labels = [
        ...(funnelVizType === FunnelVizType.Steps
            ? [
                  <>
                      <span className="flex items-center text-secondary mr-1">
                          <Tooltip title={totalRateTooltip}>
                              <IconInfo className="mr-1 text-xl shrink-0" />
                          </Tooltip>
                          <span>Total conversion rate:</span>
                      </span>
                      <span className="l4">{totalRate}</span>
                  </>,
              ]
            : []),
        ...(funnelVizType !== FunnelVizType.Trends && medianTime !== null
            ? [
                  <>
                      <span className="flex items-center text-secondary">
                          <Tooltip title={medianTimeTooltip}>
                              <IconInfo className="mr-1 text-xl shrink-0" />
                          </Tooltip>
                          <span>{medianTimeLabel}</span>
                      </span>
                      {funnelVizType === FunnelVizType.TimeToConvert && <FunnelStepsPicker />}
                      <span className="text-secondary mr-1">:</span>
                      {funnelVizType === FunnelVizType.TimeToConvert ? (
                          <span className="font-bold">{medianTime}</span>
                      ) : (
                          <Link className="font-bold" onClick={showTimeToConvert}>
                              {medianTime}
                          </Link>
                      )}
                  </>,
              ]
            : []),
        ...(funnelVizType === FunnelVizType.Trends
            ? [
                  <>
                      <span className="text-secondary">Conversion rate</span>
                      <FunnelStepsPicker />
                  </>,
              ]
            : []),

        ...(experimentUrl
            ? [
                  <LemonButton
                      key="run-experiment"
                      icon={<IconTestTube />}
                      type="secondary"
                      data-attr="create-experiment-from-insight"
                      size="xsmall"
                      tooltip={EXPERIMENT_TOOLTIP}
                      onClick={trackExperimentIntent}
                      to={experimentUrl}
                  >
                      Run experiment
                  </LemonButton>,
              ]
            : []),
    ]

    return (
        <div className="flex items-center">
            {labels.map((label, i) => (
                <React.Fragment key={i}>
                    {i > 0 && <span className="my-0.5 mx-2 border-l border-primary h-3.5" />}
                    {label}
                </React.Fragment>
            ))}
        </div>
    )
}
