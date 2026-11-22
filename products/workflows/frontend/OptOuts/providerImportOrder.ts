import type { ImportProviderOptionApi } from 'products/messaging/frontend/generated/api.schemas'

/** The page the import window was opened from. */
export type ImportEntryPoint = 'workflows' | 'templates' | 'transactional' | 'broadcasts' | 'opt-outs'

export function sortProvidersByName(providers: ImportProviderOptionApi[]): ImportProviderOptionApi[] {
    return [...providers].sort((a, b) => a.label.localeCompare(b.label, 'en', { sensitivity: 'base' }))
}
