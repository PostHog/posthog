import { useActions, useValues } from 'kea'

import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'
import { SeverityLevelsDropdown } from 'products/logs/frontend/components/LogsViewer/Filters/SeverityLevelsDropdown'

export const SeverityLevelsFilter = (): JSX.Element => {
    const { filters } = useValues(logsViewerFiltersLogic)
    const { severityLevels } = filters
    const { setSeverityLevels } = useActions(logsViewerFiltersLogic)

    return <SeverityLevelsDropdown value={severityLevels} onChange={setSeverityLevels} />
}
