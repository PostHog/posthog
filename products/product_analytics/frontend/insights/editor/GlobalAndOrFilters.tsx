import { useActions, useValues } from 'kea'

import { getProjectEventExistence } from 'lib/utils/getAppContext'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { getAllEventNames } from '~/queries/nodes/InsightViz/utils'
import { ProductAnalyticsInsightQueryNode } from '~/queries/schema/schema-general'
import { isActionsNode, isInsightQueryWithSeries } from '~/queries/utils'
import { EditorFilterProps } from '~/types'

import { getInsightPropertyFilterGroupTypes } from 'products/product_analytics/frontend/insights/editor/propertyTaxonomicGroupTypes'

import { PropertyGroupFilters } from './PropertyGroupFilters/PropertyGroupFilters'

export function GlobalAndOrFilters({ insightProps }: EditorFilterProps): JSX.Element {
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { querySource, globalFiltersUnsupported } = useValues(insightVizDataLogic(insightProps))
    const { actions: allActions } = useValues(
        actionsModel({
            shouldLoad:
                !!querySource && isInsightQueryWithSeries(querySource) && querySource.series.some(isActionsNode),
        })
    )
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))

    const { hasPageview, hasScreen } = getProjectEventExistence()

    const taxonomicGroupTypes = getInsightPropertyFilterGroupTypes({
        groupsTaxonomicTypes,
        hasPageview,
        hasScreen,
    })

    return (
        <PropertyGroupFilters
            insightProps={insightProps}
            pageKey={`${keyForInsightLogicProps('new')(insightProps)}-GlobalAndOrFilters`}
            query={querySource as ProductAnalyticsInsightQueryNode}
            setQuery={updateQuerySource}
            eventNames={getAllEventNames(querySource as ProductAnalyticsInsightQueryNode, allActions)}
            taxonomicGroupTypes={taxonomicGroupTypes}
            globalFiltersUnsupported={globalFiltersUnsupported}
        />
    )
}
