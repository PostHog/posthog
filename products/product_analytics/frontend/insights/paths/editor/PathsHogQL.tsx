import { useActions, useValues } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'

import { taxonomicEventFilterToHogQL } from '~/queries/utils'
import { EditorFilterProps } from '~/types'

import { pathsDataLogic } from 'products/product_analytics/frontend/insights/paths/pathsDataLogic'

export function PathsHogQL({ insightProps }: EditorFilterProps): JSX.Element {
    const { pathsFilter } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsDataLogic(insightProps))

    return (
        <TaxonomicPopover
            groupType={TaxonomicFilterGroupType.HogQLExpression}
            value={pathsFilter?.pathsHogQLExpression || 'event'}
            data-attr="paths-hogql-expression"
            fullWidth
            onChange={(v, g) => {
                const hogQl = taxonomicEventFilterToHogQL(g, v)
                if (hogQl) {
                    updateInsightFilter({ pathsHogQLExpression: hogQl })
                }
            }}
            groupTypes={[TaxonomicFilterGroupType.HogQLExpression]}
        />
    )
}
