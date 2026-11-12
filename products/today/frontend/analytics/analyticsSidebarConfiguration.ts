import { getCurrentUserIdOrNone } from 'lib/utils/getAppContext'
import { teamLogic } from 'scenes/teamLogic'

import type { CustomizationApi } from 'products/ui_customization/frontend/generated/api.schemas'
import { sidebarConfiguration, SidebarContextConfiguration } from 'products/ui_customization/frontend/sidebarContexts'
import type { SidebarCustomizationProps } from 'products/ui_customization/frontend/sidebarCustomizationLogic'

export const DEFAULT_ANALYTICS_SIDEBAR: CustomizationApi = {
    customized: false,
    layout: {
        version: 1,
        sections: [
            {
                id: 'browse',
                items: [
                    { type: 'link', to: { kind: 'page', page: 'analytics_all' } },
                    { type: 'link', to: { kind: 'page', page: 'analytics_mine' } },
                    { type: 'link', to: { kind: 'page', page: 'collections' } },
                    { type: 'link', to: { kind: 'page', page: 'dashboards' } },
                ],
            },
            { id: 'pinned', title: 'Pinned', items: [{ type: 'list', source: 'pinned' }] },
            { id: 'recents', title: 'Recents', items: [{ type: 'list', source: 'recents' }] },
            { id: 'by-posthog', title: 'By PostHog', icon: 'posthog', items: [{ type: 'list', source: 'by_posthog' }] },
            {
                id: 'monitor',
                title: 'Monitor',
                items: [
                    { type: 'link', to: { kind: 'page', page: 'alerts' } },
                    { type: 'link', to: { kind: 'page', page: 'subscriptions' } },
                ],
            },
        ],
    },
}

export const ANALYTICS_SIDEBAR_CONFIGURATION: SidebarContextConfiguration = {
    context: 'analytics_sidebar',
    defaults: DEFAULT_ANALYTICS_SIDEBAR,
}

export function analyticsSidebarProps(): SidebarCustomizationProps {
    return {
        configuration: sidebarConfiguration(ANALYTICS_SIDEBAR_CONFIGURATION),
        projectId: String(teamLogic.values.currentProjectId),
        userId: getCurrentUserIdOrNone() ?? '',
    }
}
