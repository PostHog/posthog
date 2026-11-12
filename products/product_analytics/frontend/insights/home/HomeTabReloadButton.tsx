import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { teamLogic } from 'scenes/teamLogic'

import { homeTabReloadLogic } from './homeTabReloadLogic'

export function HomeTabReloadButton(): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const logic = homeTabReloadLogic({ teamId: currentTeamId })
    const { areAnyLoading, reloadDisabledReason } = useValues(logic)
    const { reloadAll } = useActions(logic)

    return (
        <Button
            variant="outline"
            size="icon"
            onClick={reloadAll}
            loading={areAnyLoading}
            disabledReason={reloadDisabledReason}
            aria-label="Reload"
            tooltip="Reload"
            data-attr="home-tab-reload"
        >
            <IconRefresh />
        </Button>
    )
}
