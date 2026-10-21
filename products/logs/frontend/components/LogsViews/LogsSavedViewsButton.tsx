import { useValues } from 'kea'

import { SavedViewsButton } from 'lib/components/SavedViews/SavedViewsButton'

import { getFiltersSummaryLines } from 'products/logs/frontend/utils'

import { LogsViewsLogicProps, logsSavedViewsLogicProps, logsViewsLogic } from './logsViewsLogic'

interface LogsSavedViewsButtonProps extends LogsViewsLogicProps {
    iconOnly?: boolean
}

export function LogsSavedViewsButton({ id, iconOnly }: LogsSavedViewsButtonProps): JSX.Element {
    const { savePayload } = useValues(logsViewsLogic({ id }))

    return (
        <SavedViewsButton
            logicProps={logsSavedViewsLogicProps(id)}
            savePayload={savePayload}
            getFiltersSummaryLines={getFiltersSummaryLines}
            iconOnly={iconOnly}
        />
    )
}
