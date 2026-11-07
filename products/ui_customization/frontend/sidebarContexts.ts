import {
    uiCustomizationAnalyticsSidebarDestroy,
    uiCustomizationAnalyticsSidebarRetrieve,
    uiCustomizationAnalyticsSidebarUpdate,
} from './generated/api'
import type { SidebarConfiguration } from './sidebarCustomizationLogic'

export type SidebarContextConfiguration = Pick<SidebarConfiguration, 'context' | 'defaults'>

export function sidebarConfiguration(context: SidebarContextConfiguration): SidebarConfiguration {
    return {
        ...context,
        // Keep the persisted layout key across the product extraction.
        storageKey: 'layout.today.todayAnalyticsLogic.savedSidebar',
        resetEvent: 'analytics sidebar reset',
        retrieve: (projectId) => uiCustomizationAnalyticsSidebarRetrieve(projectId),
        reset: (projectId) => uiCustomizationAnalyticsSidebarDestroy(projectId),
        restore: (projectId, layout) => uiCustomizationAnalyticsSidebarUpdate(projectId, { layout }),
    }
}
