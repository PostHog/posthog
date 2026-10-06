import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { recipientDetailLogic } from './recipientDetailLogic'

export function OpenPreferencesPageButton(): JSX.Element {
    const { preferencesUrlLoading } = useValues(recipientDetailLogic)
    const { openPreferencesPage } = useActions(recipientDetailLogic)
    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconExternal />}
            loading={preferencesUrlLoading}
            onClick={openPreferencesPage}
            tooltip="Opens the page where this recipient manages their topics, in a new tab"
            data-attr="audience-recipient-preferences-page"
        >
            Open preferences page
        </LemonButton>
    )
}
