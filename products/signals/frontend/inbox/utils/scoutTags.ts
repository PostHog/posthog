import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'

export const MAX_SCOUT_TAGS = 10
export const MAX_SCOUT_TAG_LENGTH = 50

export function normalizeScoutTag(raw: string): string {
    return raw
        .trim()
        .toLowerCase()
        .replace(/[\s_]+/g, '-')
        .replace(/[^a-z0-9-]+/g, '')
        .replace(/-{2,}/g, '-')
        .replace(/^-+|-+$/g, '')
}

export function normalizeScoutTags(tags: string[]): string[] {
    return [...new Set(tags.map(normalizeScoutTag).filter(Boolean))].sort()
}

export interface ParsedScoutTags {
    tags: string[]
    tooLong: string[]
}

export function parseScoutTagsInput(input: string): ParsedScoutTags {
    const tags: string[] = []
    const tooLong: string[] = []

    for (const candidate of input.split(',')) {
        const tag = normalizeScoutTag(candidate)
        if (!tag) {
            continue
        }
        if (tag.length > MAX_SCOUT_TAG_LENGTH) {
            tooLong.push(tag)
        } else if (!tags.includes(tag)) {
            tags.push(tag)
        }
    }

    return { tags, tooLong }
}

export function scoutTags(config: Pick<SignalScoutConfigApi, 'tags'>): string[] {
    return config.tags ?? []
}

export interface ScoutTagsAddition {
    tags: string[] | null
    overCap: boolean
}

export function withScoutTagsAdded(existing: string[], additions: string[]): ScoutTagsAddition {
    const next = new Set([...existing, ...additions])
    if (next.size > MAX_SCOUT_TAGS) {
        return { tags: null, overCap: true }
    }
    if (next.size === existing.length) {
        return { tags: null, overCap: false }
    }
    return { tags: [...next].sort(), overCap: false }
}

export function withScoutTagRemoved(existing: string[], tag: string): string[] | null {
    if (!existing.includes(tag)) {
        return null
    }
    return existing.filter((candidate) => candidate !== tag).sort()
}

export interface ScoutTagOption {
    tag: string
    count: number
}

export function listScoutTagOptions(configs: SignalScoutConfigApi[]): ScoutTagOption[] {
    const counts = new Map<string, number>()
    for (const config of configs) {
        for (const tag of scoutTags(config)) {
            counts.set(tag, (counts.get(tag) ?? 0) + 1)
        }
    }
    return [...counts.entries()]
        .map(([tag, count]) => ({ tag, count }))
        .sort((first, second) => second.count - first.count || first.tag.localeCompare(second.tag))
}

export function configMatchesScoutTags(config: SignalScoutConfigApi, selected: string[]): boolean {
    if (selected.length === 0) {
        return true
    }
    const tags = scoutTags(config)
    return selected.some((tag) => tags.includes(tag))
}
