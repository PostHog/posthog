import { useActions, useValues } from 'kea'

import { IconChevronDown, IconEllipsis } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { teamLogic } from 'scenes/teamLogic'

import { homeDashboardChoiceLogic } from './homeDashboardChoiceLogic'

/** Opens, changes, or removes the dashboard that replaces the default product analytics dashboard. */
export function HomeDashboardMenu({
    inDashboardHeader = false,
}: {
    /** The dashboard header has its own Customize button, so this menu only changes which dashboard shows. */
    inDashboardHeader?: boolean
}): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { openHomeDashboardStarter, editHomeDashboard, restorePostHogHome } = useActions(homeDashboardChoiceLogic)
    const homeDashboardId = currentTeam?.home_tab_dashboard

    if (!homeDashboardId) {
        return (
            <Button variant="outline" onClick={openHomeDashboardStarter} data-attr="home-tab-choose-dashboard">
                Customize
            </Button>
        )
    }

    return (
        <DropdownMenu>
            {inDashboardHeader ? (
                <DropdownMenuTrigger
                    render={
                        <Button
                            variant="outline"
                            size="icon"
                            aria-label="Dashboard options"
                            tooltip="Dashboard options"
                            data-attr="home-tab-dashboard-options"
                        />
                    }
                >
                    <IconEllipsis />
                </DropdownMenuTrigger>
            ) : (
                <DropdownMenuTrigger render={<Button variant="outline" data-attr="home-tab-dashboard-options" />}>
                    Customize
                    <IconChevronDown />
                </DropdownMenuTrigger>
            )}
            <DropdownMenuContent align="end" className="min-w-48">
                {!inDashboardHeader && (
                    <DropdownMenuItem
                        onClick={() => editHomeDashboard(homeDashboardId)}
                        data-attr="home-tab-open-dashboard"
                    >
                        Edit dashboard
                    </DropdownMenuItem>
                )}
                <DropdownMenuItem onClick={openHomeDashboardStarter} data-attr="home-tab-choose-dashboard">
                    Show a different dashboard
                </DropdownMenuItem>
                <DropdownMenuItem onClick={restorePostHogHome} data-attr="home-tab-restore-posthog-home">
                    Reset to PostHog default
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
