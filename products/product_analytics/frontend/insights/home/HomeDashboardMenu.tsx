import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconEllipsis } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { homeDashboardChoiceLogic } from './homeDashboardChoiceLogic'

/** Opens, changes, or removes the dashboard that replaces the default product analytics Home. */
export function HomeDashboardMenu(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { push } = useActions(router)
    const { openHomeDashboardStarter, restorePostHogHome } = useActions(homeDashboardChoiceLogic)
    const homeDashboardId = currentTeam?.home_tab_dashboard

    if (!homeDashboardId) {
        return (
            <Button variant="outline" onClick={openHomeDashboardStarter} data-attr="home-tab-choose-dashboard">
                Make my own dashboard
            </Button>
        )
    }

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        size="icon"
                        aria-label="Home dashboard options"
                        tooltip="Home dashboard options"
                        data-attr="home-tab-dashboard-options"
                    />
                }
            >
                <IconEllipsis />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-48">
                <DropdownMenuItem
                    onClick={() => push(urls.dashboard(homeDashboardId))}
                    data-attr="home-tab-open-dashboard"
                >
                    Open dashboard
                </DropdownMenuItem>
                <DropdownMenuItem onClick={openHomeDashboardStarter} data-attr="home-tab-choose-dashboard">
                    Change Home dashboard
                </DropdownMenuItem>
                <DropdownMenuItem onClick={restorePostHogHome} data-attr="home-tab-restore-posthog-home">
                    Use default dashboard
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
