import {
    IconBell,
    IconBug,
    IconCheck,
    IconFlag,
    IconGraph,
    IconLaptop,
    IconMessage,
    IconNotification,
    IconPlug,
    IconPulse,
    IconRocket,
    IconServer,
    IconSparkles,
    IconToggle,
    IconWarning,
} from '@posthog/icons'

import { isObject } from 'lib/utils/guards'

export const SEASONAL_ITEM_ICONS = {
    bell: IconBell,
    bug: IconBug,
    check: IconCheck,
    flag: IconFlag,
    graph: IconGraph,
    laptop: IconLaptop,
    message: IconMessage,
    notification: IconNotification,
    plug: IconPlug,
    pulse: IconPulse,
    rocket: IconRocket,
    server: IconServer,
    sparkles: IconSparkles,
    toggle: IconToggle,
    warning: IconWarning,
} as const

export type SeasonalItemIcon = keyof typeof SEASONAL_ITEM_ICONS

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

function parseItem(value: unknown): SeasonalChecklistItem | null {
    if (!isObject(value)) {
        return null
    }
    const key = text(value.key)
    const title = text(value.title)
    const description = text(value.description)
    const actionLabel = optionalText(value.actionLabel)
    const url = optionalText(value.url)
    const icon = value.icon === undefined ? null : value.icon
    if (!key || !title || !description || actionLabel === undefined || url === undefined) {
        return null
    }
    if (actionLabel === null || url === null ? actionLabel !== url : !isSafeUrl(url)) {
        return null
    }
    if (icon !== null && !(typeof icon === 'string' && icon in SEASONAL_ITEM_ICONS)) {
        return null
    }
    return { key, title, description, icon: icon as SeasonalItemIcon | null, actionLabel, url }
}

export function parseSeasonalChecklist(value: unknown): SeasonalChecklist | null {
    if (!isObject(value)) {
        return null
    }
    const campaign = text(value.campaign)
    const title = text(value.title)
    const description = text(value.description)
    const reason = optionalText(value.reason)
    const badge = optionalText(value.badge)
    const bubble = textOr(value.bubble, title)
    const doneTitle = textOr(value.doneTitle, title)
    const doneDescription = textOr(value.doneDescription, description)
    if (
        !campaign ||
        !title ||
        !description ||
        reason === undefined ||
        badge === undefined ||
        !bubble ||
        !doneTitle ||
        !doneDescription
    ) {
        return null
    }

    const accessories = value.accessories ?? []
    if (
        !Array.isArray(accessories) ||
        !accessories.every((a) => SEASONAL_HOG_ACCESSORIES.includes(a as SeasonalHogAccessory))
    ) {
        return null
    }
    if (
        !['undefined', 'boolean'].includes(typeof value.snow) ||
        !['undefined', 'boolean'].includes(typeof value.lights)
    ) {
        return null
    }

    if (!Array.isArray(value.items) || value.items.length === 0 || value.items.length > SEASONAL_CHECKLIST_MAX_ITEMS) {
        return null
    }
    const items = value.items.map(parseItem)
    if (items.some((item) => item === null)) {
        return null
    }
    const validItems = items as SeasonalChecklistItem[]
    if (new Set(validItems.map((item) => item.key)).size !== validItems.length) {
        return null
    }

    return {
        campaign,
        title,
        description,
        reason,
        badge,
        bubble,
        doneTitle,
        doneDescription,
        accessories: accessories as SeasonalHogAccessory[],
        snow: value.snow === true,
        lights: value.lights === true,
        items: validItems,
    }
}
