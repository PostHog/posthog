import { identifierToHuman } from 'lib/utils/strings'

import type { BindingApi, DefinitionSourceRefApi } from './generated/api.schemas'

const KIND_LABELS: Record<string, string> = {
    action: 'action',
    alert: 'alert',
    check: 'data quality check',
    cohort: 'cohort',
    context_page: 'context page',
    dashboard: 'dashboard',
    destination: 'destination',
    endpoint: 'endpoint',
    event: 'event',
    experiment: 'experiment',
    flag: 'feature flag',
    insight: 'insight',
    metric: 'metric',
    model: 'model',
    property_group: 'property group',
    source: 'source',
    survey: 'survey',
}

// Each kind's API body paths, named the way its scene labels the field.
const FIELD_LABELS: Record<string, Record<string, string>> = {
    action: { name: 'name', description: 'description', steps: 'match groups', tags: 'tags' },
    cohort: { name: 'name', description: 'description', filters: 'criteria', is_static: 'cohort type' },
    dashboard: { name: 'name', description: 'description', tags: 'tags', tiles: 'tiles', pinned: 'pinned' },
    event: {
        description: 'description',
        tags: 'tags',
        owner: 'owner',
        verified: 'verification',
        hidden: 'visibility',
        enforcement_mode: 'schema enforcement',
        property_groups: 'property groups',
    },
    flag: {
        key: 'key',
        name: 'description',
        tags: 'tags',
        ensure_experience_continuity: 'persistence',
    },
    insight: { name: 'name', description: 'description', tags: 'tags', query: 'query', dashboards: 'dashboards' },
    property_group: { name: 'name', description: 'description', properties: 'properties' },
}

export function kindLabel(kind: string): string {
    return KIND_LABELS[kind] ?? identifierToHuman(kind).toLowerCase()
}

export function fieldLabel(kind: string, path: string): string {
    return FIELD_LABELS[kind]?.[path] ?? identifierToHuman(path.split('.').pop() ?? path).toLowerCase()
}

/** Labels for the owned fields, without duplicates, in the order the kind's scene lists them. */
export function ownedFieldLabels(kind: string, ownedFields: string[]): string[] {
    const order = Object.keys(FIELD_LABELS[kind] ?? {})
    const sorted = [...ownedFields].sort((a, b) => {
        const left = order.indexOf(a)
        const right = order.indexOf(b)
        return (left === -1 ? order.length : left) - (right === -1 ? order.length : right)
    })
    return Array.from(new Set(sorted.filter((path) => !path.startsWith('_')).map((path) => fieldLabel(kind, path))))
}

/** A field is owned when code owns it, a field inside it, or an object that contains it. */
export function isPathOwned(ownedFields: readonly string[], path: string): boolean {
    return ownedFields.some((owned) => owned === path || owned.startsWith(`${path}.`) || path.startsWith(`${owned}.`))
}

const GITHUB_REPOSITORY = /^[A-Za-z0-9-]+\/[A-Za-z0-9._-]+$/

/** A link to the definition's file on GitHub, or null when the repository is not a GitHub `owner/name`. */
export function definitionFileUrl(repository: string, source: DefinitionSourceRefApi | null): string | null {
    if (!source?.file || !GITHUB_REPOSITORY.test(repository)) {
        return null
    }
    const path = source.file
        .replace(/^\.?\//, '')
        .split('/')
        .map(encodeURIComponent)
        .join('/')
    // `HEAD` resolves to the repository's default branch, which is the branch a push comes from.
    return `https://github.com/${repository}/blob/HEAD/${path}`
}

/** The hover reason on a read-only managed field. */
export function ownedFieldReason(binding: Pick<BindingApi, 'source' | 'stack_name'>): string {
    return binding.source?.file
        ? `Managed in code. Edit ${binding.source.file} to change this.`
        : `Managed in code by the stack ${binding.stack_name}. Change this in its repository.`
}

/**
 * Whether the API refused a write because code owns the field. A global handler already tells the person which file to
 * edit, so a scene's own failure toast skips this error to avoid saying it twice.
 */
export function isManagedInCodeRefusal(error: unknown): boolean {
    const candidate = error as { status?: number; code?: string } | null
    return candidate?.status === 409 && candidate.code === 'managed_in_code'
}
