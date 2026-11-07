import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import type { AnalyticsSidebarApi, AnalyticsSidebarRequestApi } from './api.schemas'

export const getUiCustomizationAnalyticsSidebarRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/ui_customization/analytics_sidebar/`
}

/**
 * The layout of the Analytics pane in the new navigation: the person's own layout, or the default when they have not saved one. Read it before you change it, so you keep the sections the person wants. 404 when the person does not have UI customization enabled.
 * @summary Get the person's analytics sidebar
 */
export const uiCustomizationAnalyticsSidebarRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<AnalyticsSidebarApi> => {
    return apiMutator<AnalyticsSidebarApi>(getUiCustomizationAnalyticsSidebarRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getUiCustomizationAnalyticsSidebarUpdateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/ui_customization/analytics_sidebar/`
}

/**
 * Replaces the layout of the person's Analytics pane. It changes only the person who calls it, in this project. The pane shows the new layout the next time it loads. 400 lists every value that does not fit the layout schema. 404 when the person does not have UI customization enabled.
 * @summary Set the person's analytics sidebar
 */
export const uiCustomizationAnalyticsSidebarUpdate = async (
    projectId: string,
    analyticsSidebarRequestApi: AnalyticsSidebarRequestApi,
    options?: RequestInit
): Promise<AnalyticsSidebarApi> => {
    return apiMutator<AnalyticsSidebarApi>(getUiCustomizationAnalyticsSidebarUpdateUrl(projectId), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(analyticsSidebarRequestApi),
    })
}

export const getUiCustomizationAnalyticsSidebarDestroyUrl = (projectId: string) => {
    return `/api/projects/${projectId}/ui_customization/analytics_sidebar/`
}

/**
 * Removes the person's own layout, so the Analytics pane shows the default again. Returns the default layout. 404 when the person does not have UI customization enabled.
 * @summary Reset the person's analytics sidebar
 */
export const uiCustomizationAnalyticsSidebarDestroy = async (
    projectId: string,
    options?: RequestInit
): Promise<AnalyticsSidebarApi> => {
    return apiMutator<AnalyticsSidebarApi>(getUiCustomizationAnalyticsSidebarDestroyUrl(projectId), {
        ...options,
        method: 'DELETE',
    })
}
