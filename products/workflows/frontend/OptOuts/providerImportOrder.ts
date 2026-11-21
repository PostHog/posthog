import type { ImportProviderOptionApi } from 'products/messaging/frontend/generated/api.schemas'

/** The page the import window was opened from. */
export type ImportEntryPoint = 'workflows' | 'templates' | 'transactional' | 'broadcasts' | 'opt-outs'

const STEPS_FIRST: Record<ImportEntryPoint, string[]> = {
    workflows: ['automations'],
    templates: ['templates'],
    transactional: ['templates'],
    broadcasts: ['contacts', 'lists', 'mailing_lists'],
    'opt-outs': [],
}

/** Puts the tools that bring what the page is about first, keeping the API's order otherwise. */
export function orderProvidersForEntryPoint(
    providers: ImportProviderOptionApi[],
    entryPoint: ImportEntryPoint
): ImportProviderOptionApi[] {
    const wanted = STEPS_FIRST[entryPoint]
    const bringsWanted = (provider: ImportProviderOptionApi): boolean =>
        provider.steps.some((step) => wanted.includes(step.key))
    return [...providers.filter(bringsWanted), ...providers.filter((provider) => !bringsWanted(provider))]
}
