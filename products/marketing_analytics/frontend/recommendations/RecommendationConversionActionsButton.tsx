import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { conversionActionsLabel } from './conversionActions'
import { conversionActionsLogic } from './conversionActionsLogic'
import { recommendationsLogic } from './recommendationsLogic'

export function RecommendationConversionActionsButton(): JSX.Element | null {
    const { accounts, savedActions, loadFailed } = useValues(conversionActionsLogic)
    const { openEditor } = useActions(conversionActionsLogic)
    const { reportRecommendationsActionClicked } = useActions(recommendationsLogic)

    // A failed load keeps the entry point, because the editor is where the retry lives.
    if (accounts.length === 0 && savedActions.length === 0 && !loadFailed) {
        return null
    }
    return (
        <LemonButton
            size="small"
            type="tertiary"
            sideIcon={null}
            tooltip="The Google Ads conversion actions that recommendations count as conversions"
            onClick={() => {
                reportRecommendationsActionClicked('edit_conversion_actions', 'section_conversion_actions')
                openEditor()
            }}
            data-attr="marketing-recommendations-conversion-actions"
        >
            {conversionActionsLabel(savedActions)}
        </LemonButton>
    )
}
