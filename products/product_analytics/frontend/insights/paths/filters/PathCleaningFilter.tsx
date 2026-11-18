import { useActions, useValues } from 'kea'

import { PathCleaningControls } from 'lib/components/PathCleanFilters/PathCleaningControls'

import { EditorFilterProps } from '~/types'

import { pathsDataLogic } from 'products/product_analytics/frontend/insights/paths/pathsDataLogic'

export function PathCleaningFilter({ insightProps }: EditorFilterProps): JSX.Element {
    const { pathsFilter } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsDataLogic(insightProps))

    const { localPathCleaningFilters, pathReplacements } = pathsFilter || {}

    return (
        <PathCleaningControls
            localFilters={localPathCleaningFilters || []}
            setLocalFilters={(localPathCleaningFilters) => updateInsightFilter({ localPathCleaningFilters })}
            applyGlobal={!!pathReplacements}
            setApplyGlobal={(pathReplacements) => updateInsightFilter({ pathReplacements })}
        />
    )
}
