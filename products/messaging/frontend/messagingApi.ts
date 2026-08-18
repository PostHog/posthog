import * as generated from './generated/api'

type GeneratedApiAdapter = (...args: any[]) => Promise<any>

export const messagingCategoriesCreate = generated.messagingCategoriesCreate as GeneratedApiAdapter
export const messagingCategoriesList = generated.messagingCategoriesList as GeneratedApiAdapter
export const messagingCategoriesPartialUpdate = generated.messagingCategoriesPartialUpdate as GeneratedApiAdapter
export const messagingPreferencesGenerateLinkCreate =
    generated.messagingPreferencesGenerateLinkCreate as GeneratedApiAdapter
export const messagingTemplatesCreate = generated.messagingTemplatesCreate as GeneratedApiAdapter
export const messagingTemplatesList = generated.messagingTemplatesList as GeneratedApiAdapter
export const messagingTemplatesPartialUpdate = generated.messagingTemplatesPartialUpdate as GeneratedApiAdapter
export const messagingTemplatesRetrieve = generated.messagingTemplatesRetrieve as GeneratedApiAdapter
