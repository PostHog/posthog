import { createFuse } from 'lib/utils/fuseSearch'

import { StepCategory, StepProduct } from './stepAttribution'
import { StepCatalogEntry } from './stepCatalog'

// pinned: view keys are sent in analytics events and data-attr values, renaming breaks dashboards
export type StepPickerView = 'all' | 'highlights' | 'ai' | 'favorites' | 'recents' | 'posthog' | 'flow'

export type StepPickerSurface = 'tree' | 'side_panel'

export type StepPickerPickVia = 'row' | 'detail'

export type StepPickerPreferences = {
    favoriteStepIds: string[]
    recentStepIds: string[]
}

export type StepProvider = {
    id: string
    label: string
    product: StepProduct | null
    entries: StepCatalogEntry[]
}

export type StepProviderGroups = {
    posthog: StepProvider[]
    thirdParty: StepProvider[]
}

export const STEP_PICKER_VIEW_LABELS: Record<StepPickerView, string> = {
    all: 'All steps',
    highlights: 'Highlights',
    ai: 'PostHog AI',
    favorites: 'Favorites',
    recents: 'Recently used',
    posthog: 'PostHog',
    flow: 'Flow control',
}

export const STEP_PRODUCT_ORDER: StepProduct[] = [
    'workflows',
    'core',
    'support',
    'customer_analytics',
    'tasks',
    'signals',
]

export const STEP_PRODUCT_LABELS: Record<StepProduct, string> = {
    workflows: 'Workflows',
    core: 'PostHog',
    support: 'Support',
    customer_analytics: 'Customer analytics',
    tasks: 'Tasks',
    signals: 'Signals',
}

export const STEP_PRODUCT_DESCRIPTIONS: Record<StepProduct, string> = {
    workflows: 'Send messages, call webhooks and run AI steps from this workflow.',
    core: 'Write events, person properties and group properties back into PostHog.',
    support: 'Read and update support tickets and reply to customers.',
    customer_analytics: 'Keep accounts, tags, relationships and tasks up to date.',
    tasks: 'Hand work to an AI agent.',
    signals: 'Start a scout run.',
}

export const STEP_CATEGORY_LABELS: Record<StepCategory, string> = {
    messaging: 'Messaging',
    ai: 'AI',
    flow: 'Flow control',
    posthog_data: 'PostHog data',
    support: 'Support',
    customer_analytics: 'Customer analytics',
    crm: 'CRM and sales',
    marketing: 'Marketing automation',
    analytics: 'Analytics',
    ads: 'Ad conversions',
    developer: 'Developer tools',
    data: 'Data and storage',
}

const HIGHLIGHT_ORDER = [
    'template-posthog-create-task',
    'template-posthog-classify',
    'template-posthog-run-scout',
    'template-posthog-send-ticket-message',
    'template-posthog-create-customer-task',
    'template-email',
    'template-slack',
    'step-conditional_branch',
]

export function stepTitle(entry: StepCatalogEntry): string {
    return entry.operation ?? entry.name
}

export function stepCountLabel(count: number): string {
    return count === 1 ? '1 step' : `${count} steps`
}

export function providerLabelOf(entry: StepCatalogEntry): string {
    return entry.product ? STEP_PRODUCT_LABELS[entry.product] : (entry.vendor ?? entry.name)
}

function productProviders(entries: StepCatalogEntry[]): StepProvider[] {
    return STEP_PRODUCT_ORDER.map((product) => ({
        id: `product:${product}`,
        label: STEP_PRODUCT_LABELS[product],
        product,
        entries: entries.filter((entry) => entry.product === product && entry.category !== 'flow'),
    })).filter((provider) => provider.entries.length > 0)
}

function vendorProviders(entries: StepCatalogEntry[]): StepProvider[] {
    const byVendor = new Map<string, StepCatalogEntry[]>()
    for (const entry of entries.filter((candidate) => candidate.origin === 'third_party')) {
        const vendor = providerLabelOf(entry)
        byVendor.set(vendor, [...(byVendor.get(vendor) ?? []), entry])
    }
    return [...byVendor.entries()]
        .map(([vendor, vendorEntries]) => ({
            id: `vendor:${vendor}`,
            label: vendor,
            product: null,
            entries: vendorEntries,
        }))
        .sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: 'base' }))
}

export function groupProviders(entries: StepCatalogEntry[]): StepProviderGroups {
    return { posthog: productProviders(entries), thirdParty: vendorProviders(entries) }
}

export const STEP_PICKER_VIEWS: StepPickerView[] = [
    'all',
    'highlights',
    'ai',
    'favorites',
    'recents',
    'posthog',
    'flow',
]

const ALWAYS_VISIBLE_VIEWS: StepPickerView[] = ['all', 'favorites', 'recents']

function stepsWithIds(ids: string[], entries: StepCatalogEntry[]): StepCatalogEntry[] {
    return ids
        .map((id) => entries.find((entry) => entry.id === id))
        .filter((entry): entry is StepCatalogEntry => !!entry)
}

export function stepsForView(
    view: StepPickerView,
    entries: StepCatalogEntry[],
    preferences: StepPickerPreferences
): StepCatalogEntry[] {
    switch (view) {
        case 'highlights':
            return stepsWithIds(HIGHLIGHT_ORDER, entries)
        case 'favorites':
            return stepsWithIds(preferences.favoriteStepIds, entries)
        case 'recents':
            return stepsWithIds(preferences.recentStepIds, entries)
        case 'ai':
            return entries.filter((entry) => entry.category === 'ai')
        case 'flow':
            return entries.filter((entry) => entry.category === 'flow')
        case 'posthog':
            return entries.filter((entry) => entry.origin === 'posthog')
        case 'all':
            return entries
    }
}

export function visibleViews(entries: StepCatalogEntry[], preferences: StepPickerPreferences): StepPickerView[] {
    return STEP_PICKER_VIEWS.filter(
        (view) => ALWAYS_VISIBLE_VIEWS.includes(view) || stepsForView(view, entries, preferences).length > 0
    )
}

type SearchableStep = {
    entry: StepCatalogEntry
    name: string
    operation: string
    description: string
    vendor: string
    product: string
    category: string
    tags: string[]
}

export function searchSteps(entries: StepCatalogEntry[], query: string): StepCatalogEntry[] {
    const searchable: SearchableStep[] = entries.map((entry) => ({
        entry,
        name: entry.name,
        operation: entry.operation ?? '',
        description: entry.description,
        vendor: entry.vendor ?? '',
        product: entry.product ? STEP_PRODUCT_LABELS[entry.product] : '',
        category: entry.category ? STEP_CATEGORY_LABELS[entry.category] : '',
        tags: entry.tags,
    }))
    return createFuse(searchable, {
        keys: ['name', 'operation', 'description', 'vendor', 'product', 'category', 'tags'],
    })
        .search(query.trim())
        .map((result) => result.item.entry)
}
