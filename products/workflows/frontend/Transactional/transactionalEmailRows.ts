import type { UserBasicType } from '~/types'

import type { CodeEmailApi, MessageTemplateApi } from 'products/messaging/frontend/generated/api.schemas'

export type ManagedBy = 'all' | 'code' | 'posthog'

export interface TransactionalEmailsFilters {
    search: string
    createdBy: number | null
    tags: string[]
    managedBy: ManagedBy
}

export const DEFAULT_FILTERS: TransactionalEmailsFilters = { search: '', createdBy: null, tags: [], managedBy: 'all' }

interface RowFields {
    id: string
    name: string
    description: string
    tags: string[]
    sensitive: boolean
    hog_flow_id: string | null
    created_by: UserBasicType | null
    updated_at: string | null
}

/** One row of the Transactional emails list: a template designed in PostHog, or an email your code sends. */
export type TransactionalEmailRow = RowFields &
    ({ source: 'posthog'; template: MessageTemplateApi } | { source: 'code'; codeEmail: CodeEmailApi })

export function templateRow(template: MessageTemplateApi): TransactionalEmailRow {
    return {
        source: 'posthog',
        template,
        id: template.id,
        name: template.name,
        description: template.description ?? '',
        tags: template.tags ?? [],
        sensitive: !!template.sensitive,
        hog_flow_id: template.transactional_hog_flow_id ?? null,
        created_by: template.created_by as UserBasicType,
        updated_at: template.updated_at,
    }
}

export function codeEmailRow(codeEmail: CodeEmailApi): TransactionalEmailRow {
    return {
        source: 'code',
        codeEmail,
        id: codeEmail.id,
        name: codeEmail.key,
        description: codeEmail.description,
        tags: codeEmail.tags,
        sensitive: codeEmail.sensitive,
        hog_flow_id: codeEmail.hog_flow_id,
        created_by: null,
        updated_at: null,
    }
}

export function filterTransactionalEmails(
    rows: TransactionalEmailRow[],
    filters: Partial<TransactionalEmailsFilters>
): TransactionalEmailRow[] {
    const { search, createdBy, tags, managedBy } = { ...DEFAULT_FILTERS, ...filters }
    const lowerSearch = search.toLowerCase()
    return rows.filter(
        (row) =>
            (managedBy === 'all' || row.source === managedBy) &&
            // Your code creates a code email, so filtering by a person leaves only templates.
            (createdBy == null || row.created_by?.id === createdBy) &&
            (!tags.length || row.tags.some((tag) => tags.includes(tag))) &&
            (!lowerSearch ||
                [row.name, row.description, ...row.tags].some((text) => text.toLowerCase().includes(lowerSearch)))
    )
}
