import './FunnelsQuerySteps.scss'

import { useActions, useValues } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { getProjectEventExistence } from 'lib/utils/getAppContext'
import { SeriesActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { getInsightPropertyFilterGroupTypes } from 'scenes/insights/utils/propertyTaxonomicGroupTypes'

import { groupsModel } from '~/models/groupsModel'
import { NodeKind } from '~/queries/schema/schema-general'
import { isInsightQueryNode } from '~/queries/utils'
import { EditorFilterProps, InsightType } from '~/types'

import { FunnelDataWarehouseStepDefinitionPopover } from './FunnelDataWarehouseStepDefinitionPopover'

export const FUNNEL_STEP_COUNT_LIMIT = 30

export function FunnelsQuerySteps({ insightProps }: EditorFilterProps): JSX.Element | null {
    const { series, querySource, isBreakdownSeries, seriesMathAvailability } = useValues(
        insightVizDataLogic(insightProps)
    )
    const { updateSeries } = useActions(insightVizDataLogic(insightProps))
    const { hasPageview, hasScreen } = getProjectEventExistence()

    const { groupsTaxonomicTypes } = useValues(groupsModel)

    if (!isInsightQueryNode(querySource)) {
        return null
    }

    const filterSteps = series || []
    const showSeriesIndicator = (series || []).length > 0

    // TODO: Sort out title offset
    return (
        <>
            <div className="FunnelsQuerySteps">
                <SeriesActionFilter
                    allowBehavioralPropertyFilter
                    bordered={false}
                    series={filterSteps}
                    onChange={updateSeries}
                    insightType={InsightType.FUNNELS}
                    hasBreakdown={isBreakdownSeries}
                    dataWarehouseNodeKind={NodeKind.FunnelsDataWarehouseNode}
                    typeKey={keyForInsightLogicProps('new')(insightProps)}
                    mathAvailability={seriesMathAvailability}
                    hideDeleteBtn={filterSteps.length === 1}
                    buttonCopy="Add step"
                    showSeriesIndicator={showSeriesIndicator}
                    seriesIndicatorType="numeric"
                    entitiesLimit={FUNNEL_STEP_COUNT_LIMIT}
                    sortable
                    showNestedArrow
                    propertiesTaxonomicGroupTypes={getInsightPropertyFilterGroupTypes({
                        groupsTaxonomicTypes,
                        hasPageview,
                        hasScreen,
                    })}
                    addFilterDocLink="https://posthog.com/docs/product-analytics/trends/filters"
                    actionsTaxonomicGroupTypes={[
                        TaxonomicFilterGroupType.Events,
                        TaxonomicFilterGroupType.Actions,
                        ...(hasPageview ? [TaxonomicFilterGroupType.PageviewEvents] : []),
                        ...(hasScreen ? [TaxonomicFilterGroupType.ScreenEvents] : []),
                        TaxonomicFilterGroupType.AutocaptureEvents,
                        TaxonomicFilterGroupType.DataWarehouse,
                    ]}
                    flagCallsFromFlagEvaluations
                    definitionPopoverRenderer={FunnelDataWarehouseStepDefinitionPopover}
                    dataWarehousePopoverFields={[
                        {
                            key: 'id_field',
                            label: 'Unique ID',
                        },
                        {
                            key: 'timestamp_field',
                            label: 'Timestamp',
                        },
                        {
                            key: 'aggregation_target_field',
                            label: 'Aggregation target',
                            allowHogQL: true,
                        },
                    ]}
                />
            </div>
        </>
    )
}
