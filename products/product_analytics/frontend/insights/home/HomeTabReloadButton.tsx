import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { teamLogic } from 'scenes/teamLogic'

import { homeTabReloadLogic } from './homeTabReloadLogic'

export function HomeTabReloadButton(): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const { currentTeamId } = useValues(teamLogic)
    const logic = homeTabReloadLogic({ teamId: currentTeamId })
    const { areAnyLoading, reloadDisabledReason } = useValues(logic)
    const { reloadAll } = useActions(logic)

    if (!todayRailNav) {
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
