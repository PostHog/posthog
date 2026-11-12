import { uiCustomizationDestroy, uiCustomizationRetrieve, uiCustomizationUpdate } from './generated/api'
import type { SidebarConfiguration } from './sidebarCustomizationLogic'

type SupportedContext = Parameters<typeof uiCustomizationRetrieve>[1]

export type SidebarContextConfiguration = Pick<SidebarConfiguration, 'defaults'> & { context: SupportedContext }

const contextDefinitions: Record<SupportedContext, { resetEvent: string }> = {
    analytics_sidebar: { resetEvent: 'analytics sidebar reset' },
}

export function sidebarConfiguration(configuration: SidebarContextConfiguration): SidebarConfiguration {
    const { context } = configuration
    return {
        ...configuration,
        // Context is part of the persistence prefix, alongside the user and project.
        storageKey: 'uiCustomization.savedSidebar',
        ...contextDefinitions[context],
        retrieve: (projectId, signal) => uiCustomizationRetrieve(projectId, context, { signal }),
        reset: (projectId, signal) => uiCustomizationDestroy(projectId, context, { signal }),
        restore: (projectId, layout, signal) => uiCustomizationUpdate(projectId, context, { layout }, { signal }),
    }
}
