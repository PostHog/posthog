import { MessageTemplate } from './types'

export interface MessageTemplateFilters {
    search?: string
    tags?: string[]
    createdBy?: number | null
    transactionalOnly?: boolean
}

export function filterMessageTemplates(
    templates: MessageTemplate[],
    { search, tags, createdBy, transactionalOnly }: MessageTemplateFilters
): MessageTemplate[] {
    let filtered = templates
    if (search) {
        const lowerSearch = search.toLowerCase()
        filtered = filtered.filter(
            (t) =>
                (t.name ?? '').toLowerCase().includes(lowerSearch) ||
                (t.description ?? '').toLowerCase().includes(lowerSearch) ||
                (t.tags ?? []).some((tag) => tag.toLowerCase().includes(lowerSearch))
        )
    }
    if (tags?.length) {
        filtered = filtered.filter((t) => (t.tags ?? []).some((tag) => tags.includes(tag)))
    }
    if (createdBy != null) {
        filtered = filtered.filter((t) => t.created_by?.id === createdBy)
    }
    if (transactionalOnly) {
        filtered = filtered.filter((t) => !!t.transactional_hog_flow_id)
    }
    return filtered
}
