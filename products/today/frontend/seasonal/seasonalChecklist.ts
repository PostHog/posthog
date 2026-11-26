import { isObject } from 'lib/utils/guards'

export const SEASONAL_ITEM_ICONS = [
    'bell',
    'bug',
    'check',
    'flag',
    'graph',
    'laptop',
    'message',
    'notification',
    'plug',
    'pulse',
    'rocket',
    'server',
    'sparkles',
    'toggle',
    'warning',
] as const

export type SeasonalItemIcon = (typeof SEASONAL_ITEM_ICONS)[number]

export const SEASONAL_HOG_ACCESSORIES = [
    'beret',
    'cap',
    'chef',
    'cowboy',
    'eyepatch',
    'flag',
    'glasses',
    'graduation',
    'parrot',
    'party',
    'pineapple',
    'sunglasses',
    'tophat',
    'xmas-antlers',
    'xmas-hat',
    'xmas-scarf',
] as const

export type SeasonalHogAccessory = (typeof SEASONAL_HOG_ACCESSORIES)[number]

export const SEASONAL_CHECKLIST_MAX_ITEMS = 6

export interface SeasonalChecklistItem {
    key: string
    title: string
    description: string
    icon: SeasonalItemIcon | null
    actionLabel: string | null
    url: string | null
}

export interface SeasonalChecklist {
    campaign: string
    title: string
    description: string
    reason: string | null
    badge: string | null
    bubble: string
    doneTitle: string
    doneDescription: string
    accessories: SeasonalHogAccessory[]
    snow: boolean
    lights: boolean
    items: SeasonalChecklistItem[]
}

const text = (value: unknown): string | null =>
    typeof value === 'string' && value.trim().length > 0 ? value.trim() : null

const textOr = (value: unknown, fallback: string | null): string | null =>
    value === undefined ? fallback : text(value)

const optionalText = (value: unknown): string | null | undefined =>
    value === undefined ? null : (text(value) ?? undefined)

const isSafeUrl = (url: string): boolean => (url.startsWith('/') && !url.startsWith('//')) || url.startsWith('https://')

const isOptionalBoolean = (value: unknown): boolean => value === undefined || typeof value === 'boolean'

const isIcon = (value: unknown): value is SeasonalItemIcon | null =>
    value === null || SEASONAL_ITEM_ICONS.includes(value as SeasonalItemIcon)

function parseAction(value: Record<string, unknown>): Pick<SeasonalChecklistItem, 'actionLabel' | 'url'> | null {
    const actionLabel = optionalText(value.actionLabel)
    const url = optionalText(value.url)
    if (actionLabel === undefined || url === undefined) {
        return null
    }
    if (actionLabel === null || url === null) {
        return actionLabel === url ? { actionLabel, url } : null
    }
    return isSafeUrl(url) ? { actionLabel, url } : null
}

function parseItem(value: unknown): SeasonalChecklistItem | null {
    if (!isObject(value)) {
        return null
    }
    const key = text(value.key)
    const title = text(value.title)
    const description = text(value.description)
    const icon = value.icon ?? null
    const action = parseAction(value)
    if (!key || !title || !description || !action || !isIcon(icon)) {
        return null
    }
    return { key, title, description, icon, ...action }
}

function parseItems(value: unknown): SeasonalChecklistItem[] | null {
    if (!Array.isArray(value) || value.length === 0 || value.length > SEASONAL_CHECKLIST_MAX_ITEMS) {
        return null
    }
    const items = value.map(parseItem)
    if (items.some((item) => item === null)) {
        return null
    }
    const valid = items as SeasonalChecklistItem[]
    return new Set(valid.map((item) => item.key)).size === valid.length ? valid : null
}

function parseAccessories(value: unknown): SeasonalHogAccessory[] | null {
    const accessories = value ?? []
    return Array.isArray(accessories) &&
        accessories.every((accessory) => SEASONAL_HOG_ACCESSORIES.includes(accessory as SeasonalHogAccessory))
        ? (accessories as SeasonalHogAccessory[])
        : null
}

type SeasonalChecklistCopy = Pick<
    SeasonalChecklist,
    'campaign' | 'title' | 'description' | 'reason' | 'badge' | 'bubble' | 'doneTitle' | 'doneDescription'
>

function parseCopy(value: Record<string, unknown>): SeasonalChecklistCopy | null {
    const campaign = text(value.campaign)
    const title = text(value.title)
    const description = text(value.description)
    if (!campaign || !title || !description) {
        return null
    }
    const reason = optionalText(value.reason)
    const badge = optionalText(value.badge)
    const bubble = textOr(value.bubble, title)
    const doneTitle = textOr(value.doneTitle, title)
    const doneDescription = textOr(value.doneDescription, description)
    if (reason === undefined || badge === undefined || !bubble || !doneTitle || !doneDescription) {
        return null
    }
    return { campaign, title, description, reason, badge, bubble, doneTitle, doneDescription }
}

export function parseSeasonalChecklist(value: unknown): SeasonalChecklist | null {
    if (!isObject(value) || !isOptionalBoolean(value.snow) || !isOptionalBoolean(value.lights)) {
        return null
    }
    const copy = parseCopy(value)
    const accessories = parseAccessories(value.accessories)
    const items = parseItems(value.items)
    if (!copy || !accessories || !items) {
        return null
    }
    return { ...copy, accessories, snow: value.snow === true, lights: value.lights === true, items }
}
