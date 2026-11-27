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
import type { CustomizationApi, CustomizationDescriptionApi, CustomizationRequestApi } from './api.schemas'

export const getUiCustomizationRetrieveUrl = (projectId: string, context: 'analytics_sidebar') => {
    return `/api/projects/${projectId}/ui_customization/${context}/`
}

/**
 * Returns the person's layout for the selected context, or its default. Read it before changing it. Unknown contexts and people without UI customization enabled receive 404.
 * @summary Get the person's UI customization
 */
export const uiCustomizationRetrieve = async (
    projectId: string,
    context: 'analytics_sidebar',
    options?: RequestInit
): Promise<CustomizationApi> => {
    return apiMutator<CustomizationApi>(getUiCustomizationRetrieveUrl(projectId, context), {
        ...options,
        method: 'GET',
    })
}

export const getUiCustomizationUpdateUrl = (projectId: string, context: 'analytics_sidebar') => {
    return `/api/projects/${projectId}/ui_customization/${context}/`
}

/**
 * Replaces the person's layout for the selected context in this project. The context defines its allowed layout schema and limits. Unknown contexts and people without UI customization enabled receive 404.
 * @summary Set the person's UI customization
 */
export const uiCustomizationUpdate = async (
    projectId: string,
    context: 'analytics_sidebar',
    customizationRequestApi: CustomizationRequestApi,
    options?: RequestInit
): Promise<CustomizationApi> => {
    return apiMutator<CustomizationApi>(getUiCustomizationUpdateUrl(projectId, context), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(customizationRequestApi),
    })
}

export const getUiCustomizationDestroyUrl = (projectId: string, context: 'analytics_sidebar') => {
    return `/api/projects/${projectId}/ui_customization/${context}/`
}

/**
 * Removes the person's saved layout for the selected context and returns its default. Unknown contexts and people without UI customization enabled receive 404.
 * @summary Reset the person's UI customization
 */
export const uiCustomizationDestroy = async (
    projectId: string,
    context: 'analytics_sidebar',
    options?: RequestInit
): Promise<CustomizationApi> => {
    return apiMutator<CustomizationApi>(getUiCustomizationDestroyUrl(projectId, context), {
        ...options,
        method: 'DELETE',
    })
}

export const getUiCustomizationDescribeUrl = (projectId: string, context: 'analytics_sidebar') => {
    return `/api/projects/${projectId}/ui_customization/${context}/schema/`
}

/**
 * Returns the layout validation schema and defaults for a supported context without reading or changing the person's saved layout. Unknown contexts and people without UI customization enabled receive 404.
 * @summary Describe a UI customization context
 */
export const uiCustomizationDescribe = async (
    projectId: string,
    context: 'analytics_sidebar',
    options?: RequestInit
): Promise<CustomizationDescriptionApi> => {
    return apiMutator<CustomizationDescriptionApi>(getUiCustomizationDescribeUrl(projectId, context), {
        ...options,
        method: 'GET',
    })
}
