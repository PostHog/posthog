import { useActions, useValues } from 'kea'
import React from 'react'

import { IconInfo, IconTestTube } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { FEATURE_FLAGS } from 'lib/constants'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import { getExperimentMetricFromInsight } from 'scenes/experiments/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { FunnelVizType, type InsightModel } from '~/types'

import { FunnelStepsPicker } from './filters/FunnelStepsPicker'
import { funnelDataLogic } from './funnelDataLogic'
import { getLargestStepDrop } from './funnelUtils'
import { getActionFilterFromFunnelStep } from './shared/funnelStepTableUtils'

export function FunnelCanvasLabel(): JSX.Element | null {
    const { insightProps, insight, supportsCreatingExperiment, derivedName } = useValues(insightLogic)
    const { conversionMetrics, aggregationTargetLabel, funnelVizType, steps } = useValues(funnelDataLogic(insightProps))
    const { featureFlags } = useValues(featureFlagLogic)
    const showStepTotals =
        !!featureFlags[FEATURE_FLAGS.FUNNEL_STEPS_BAR_LABELS] &&
        funnelVizType === FunnelVizType.Steps &&
        steps.length > 1
    const largestDrop = showStepTotals ? getLargestStepDrop(steps) : null
    const largestDropStep = largestDrop ? steps[largestDrop.stepIndex] : null
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))
    const { addProductIntentForCrossSell } = useActions(teamLogic)

    const labels = [
        ...(funnelVizType === FunnelVizType.Steps
            ? [
                  <>
                      <span className="flex items-center text-secondary mr-1">
                          <Tooltip
                              title={`Overall conversion rate for all ${aggregationTargetLabel.plural} on the entire funnel.`}
                          >
                              <IconInfo className="mr-1 text-xl shrink-0" />
                          </Tooltip>
                          <span>Total conversion rate:</span>
                      </span>
                      <span className="l4">{percentage(conversionMetrics.totalRate, 2, true)}</span>
                      {showStepTotals && (
                          <span className="ml-1 text-secondary">
                              (<span translate="no">{humanFriendlyNumber(steps[steps.length - 1].count)}</span> of{' '}
                              <span translate="no">{humanFriendlyNumber(steps[0].count)}</span>{' '}
                              <span>
                                  {`${pluralize(steps[0].count, aggregationTargetLabel.singular, aggregationTargetLabel.plural, false)})`}
                              </span>
                          </span>
                      )}
                  </>,
              ]
            : []),
        ...(largestDrop && largestDropStep
            ? [
                  <>
                      <span className="mr-1 text-secondary">Largest drop-off:</span>
                      <span className="font-semibold">
                          <EntityFilterInfo filter={getActionFilterFromFunnelStep(largestDropStep)} showSingleName />
                      </span>
                      <span className="ml-1 font-semibold text-danger" translate="no">
                          {`(${percentage(largestDrop.dropOffRate, 0)})`}
                      </span>
                  </>,
              ]
            : []),
        ...(funnelVizType !== FunnelVizType.Trends && conversionMetrics.medianTime != null
            ? [
                  <>
                      <span className="flex items-center text-secondary">
                          <Tooltip
                              title={`Median (50th percentile) of the total time each ${aggregationTargetLabel.singular} spent in the entire funnel.`}
                          >
                              <IconInfo className="mr-1 text-xl shrink-0" />
                          </Tooltip>
                          <span>Median time to convert</span>
                      </span>
                      {funnelVizType === FunnelVizType.TimeToConvert && <FunnelStepsPicker />}
                      <span className="text-secondary mr-1">:</span>
                      {funnelVizType === FunnelVizType.TimeToConvert ? (
                          <span className="font-bold">{humanFriendlyDuration(conversionMetrics.medianTime)}</span>
                      ) : (
                          <Link
                              className="font-bold"
                              onClick={() => updateInsightFilter({ funnelVizType: FunnelVizType.TimeToConvert })}
                          >
                              {humanFriendlyDuration(conversionMetrics.medianTime)}
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

        ...(supportsCreatingExperiment
            ? [
                  <LemonButton
                      key="run-experiment"
                      icon={<IconTestTube />}
                      type="secondary"
                      data-attr="create-experiment-from-insight"
                      size="xsmall"
                      tooltip="Create a draft experiment with the metric from this funnel."
                      onClick={() =>
                          addProductIntentForCrossSell({
                              from: ProductKey.PRODUCT_ANALYTICS,
                              to: ProductKey.EXPERIMENTS,
                              intent_context: ProductIntentContext.CREATE_EXPERIMENT_FROM_FUNNEL_BUTTON,
                          })
                      }
                      to={urls.experiment('new', null, {
                          metric: getExperimentMetricFromInsight(insight as InsightModel),
                          name: insight.name || insight.derived_name || derivedName,
                      })}
                  >
                      Run experiment
                  </LemonButton>,
              ]
            : []),
    ]

    return (
        <div className="flex flex-wrap items-center gap-y-1">
            {labels.map((label, i) => (
                <React.Fragment key={i}>
                    {i > 0 && <span className="my-0.5 mx-2 border-l border-primary h-3.5" />}
                    {label}
                </React.Fragment>
            ))}
        </div>
    )
}
