import { useActions, useValues } from 'kea'

import { IconDashboard, IconPencil, IconRefresh, IconRevert } from '@posthog/icons'

import { teamLogic } from 'scenes/teamLogic'

import type { SceneAction, SceneActionGroup } from '~/layout/scenes/sceneActions/sceneActionModel'

import { homeDashboardChoiceLogic } from './homeDashboardChoiceLogic'

/** The scene actions for `HomeDashboardMenu`: open, change, or remove the dashboard that replaces the default one. */
export function useHomeDashboardActions(
    dataAttrKey: string,
    { group = 'edit', section = 'customize' }: { group?: SceneActionGroup; section?: string } = {}
): SceneAction[] {
    const { currentTeam } = useValues(teamLogic)
    const { openHomeDashboardStarter, editHomeDashboard, restorePostHogHome } = useActions(homeDashboardChoiceLogic)
    const homeDashboardId = currentTeam?.home_tab_dashboard

    if (!homeDashboardId) {
        return [
            {
                group,
                section,
                // pinned: data-attr values are wire strings
                id: 'home-tab-choose-dashboard',
                label: 'Customize',
                icon: <IconDashboard />,
                opensFloatingUi: true,
                onSelect: () => openHomeDashboardStarter(),
            },
        ]
    }
    return [
        {
            group,
            section,
            type: 'submenu',
            id: `${dataAttrKey}-menubar-customize`,
            label: 'Customize',
            icon: <IconDashboard />,
            items: [
                {
                    // pinned: data-attr values are wire strings
                    id: 'home-tab-open-dashboard',
                    label: 'Edit dashboard',
                    icon: <IconPencil />,
                    onSelect: () => editHomeDashboard(homeDashboardId),
                },
                {
                    id: 'home-tab-choose-dashboard',
                    label: 'Show a different dashboard',
                    icon: <IconRefresh />,
                    opensFloatingUi: true,
                    onSelect: () => openHomeDashboardStarter(),
                },
                {
                    id: 'home-tab-restore-posthog-home',
                    label: 'Reset to PostHog default',
                    icon: <IconRevert />,
                    onSelect: () => restorePostHogHome(),
                },
            ],
        },
    ]
}
