import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { teamLogic } from 'scenes/teamLogic'

import { homeTabReloadLogic } from './homeTabReloadLogic'

export function HomeTabReloadButton(): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const logic = homeTabReloadLogic({ teamId: currentTeamId })
    const { areAnyLoading, reloadDisabledReason } = useValues(logic)
    const { reloadAll } = useActions(logic)

    return (
        <LemonButton
            type="secondary"
            size="small"
            onClick={reloadAll}
            icon={areAnyLoading ? <Spinner textColored /> : <IconRefresh />}
            disabledReason={reloadDisabledReason}
            tooltip="Reload"
            data-attr="home-tab-reload"
        />
    )
}
