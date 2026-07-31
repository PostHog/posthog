import type { z } from 'zod'

import { ConversationsTicketGroupsGetSchema, ConversationsTicketGroupsUpdateSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

// The SLA states a ticket can be in — mirrors SLA_STATES in backend/sla.py.
// All three require a deadline to exist, so a ticket with no SLA is in none of
// them; `sla_due_at` is_set/is_not_set is the filter for that separate question.
const SLA_STATES = ['breached', 'at-risk', 'on-track'] as const
type SlaState = (typeof SLA_STATES)[number]

/** One filter of a ticket group, as stored in
 *  `conversations_settings.ticket_groups[].filters`. The vocabulary mirrors
 *  products/conversations/backend/ticket_groups.py — the write validator
 *  there is the authority. */
export type TicketGroupFilter =
    | { type: 'ticket_tags'; operator: 'any_of'; value: string[] }
    | { type: 'ticket_property'; key: 'channel_source' | 'status' | 'priority'; operator: 'in'; value: string[] }
    | { type: 'ticket_property'; key: 'email_from'; operator: 'icontains'; value: string }
    | { type: 'ticket_property'; key: 'sla_due_at'; operator: 'is_set' | 'is_not_set' }
    | { type: 'ticket_property'; key: 'sla_state'; operator: 'in'; value: SlaState[] }
    | { type: 'ticket_property'; key: 'created_at'; operator: 'date_before' | 'date_after'; value: string }
    | { type: 'sql'; expression: string }

/** One of the team's ticket groups. List order is priority order (first =
 *  highest); a ticket takes the FIRST group whose filters ALL match, and
 *  tickets matching no group rank with the first. */
export type TicketGroup = { label: string; filters: TicketGroupFilter[] }

type GetParams = z.infer<typeof ConversationsTicketGroupsGetSchema>
type UpdateParams = z.infer<typeof ConversationsTicketGroupsUpdateSchema>

type GetResult = {
    customized: boolean
    groups: TicketGroup[] | null
    message: string
    settings_url: string
}

type UpdateResult = {
    applied: boolean
    groups: TicketGroup[] | null
    message: string
    settings_url: string
}

// The full ticket_property vocabulary: valid operators per key — mirrors
// _PROPERTY_OPERATORS in the backend module.
const PROPERTY_OPERATORS: Record<string, readonly string[]> = {
    channel_source: ['in'],
    status: ['in'],
    priority: ['in'],
    email_from: ['icontains'],
    sla_due_at: ['is_set', 'is_not_set'],
    sla_state: ['in'],
    created_at: ['date_before', 'date_after'],
}

// Mirrors MAX_SQL_FILTERS in backend/ticket_groups.py and
// MAX_SQL_EXPRESSION_LENGTH in backend/ticket_group_sql.py. SQL filters are the
// escape hatch, not the main vocabulary, so both caps are deliberately tight.
const MAX_SQL_FILTERS = 5
const MAX_SQL_EXPRESSION_LENGTH = 1000

// The shared created_at date grammar — these regexes are duplicated verbatim
// from ticket_groups.py / the frontend's ticketGroups.ts.
const RELATIVE_DATE_REGEX = /^-([1-9][0-9]*)([hdwmy])(Start|End)?$/
// Same shape the backend/frontend enforce, with capture groups so the
// calendar (month/day/hour ranges) can be validated from components.
const ISO_DATE_COMPONENTS_REGEX =
    /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?)?$/
const MAX_RELATIVE_NUMBER = 1000

function isValidDateValue(value: string): boolean {
    const relativeMatch = RELATIVE_DATE_REGEX.exec(value)
    if (relativeMatch) {
        return Number(relativeMatch[1]) <= MAX_RELATIVE_NUMBER
    }
    // The regex constrains the shape; validate the calendar from the
    // components directly (V8's Date is too forgiving — it rolls 2026-02-30
    // into March and allows hour 24 and year 0000, all of which the backend's
    // fromisoformat rejects).
    const match = ISO_DATE_COMPONENTS_REGEX.exec(value)
    if (!match) {
        return false
    }
    const year = Number(match[1])
    const month = Number(match[2])
    const day = Number(match[3])
    if (year < 1 || month < 1 || month > 12) {
        return false
    }
    const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate()
    if (day < 1 || day > daysInMonth) {
        return false
    }
    if (match[4] !== undefined && (Number(match[4]) > 23 || Number(match[5]) > 59)) {
        return false
    }
    if (match[6] !== undefined && Number(match[6]) > 59) {
        return false
    }
    return true
}

const isStringList = (value: unknown): value is string[] =>
    Array.isArray(value) && value.every((item) => typeof item === 'string')

/** Enough shape to treat as a saved filter — mirrors the backend's read-side
 *  _is_structurally_usable_filter (the write validator is stricter). */
function isStructurallyUsableFilter(raw: unknown): boolean {
    if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
        return false
    }
    const filter = raw as Record<string, unknown>
    if (filter.type === 'ticket_tags') {
        return filter.operator === 'any_of' && isStringList(filter.value)
    }
    if (filter.type === 'sql') {
        // Compilability is the write validator's business; a stored expression
        // that no longer compiles matches nothing rather than failing the read.
        return typeof filter.expression === 'string' && filter.expression.trim().length > 0
    }
    if (filter.type === 'ticket_property') {
        const key = filter.key
        const operator = filter.operator
        if (typeof key !== 'string' || typeof operator !== 'string' || !PROPERTY_OPERATORS[key]?.includes(operator)) {
            return false
        }
        if (operator === 'in') {
            return isStringList(filter.value)
        }
        if (operator === 'is_set' || operator === 'is_not_set') {
            return true // no value needed
        }
        // icontains / date_before / date_after — only the type matters here;
        // the backend treats a garbage date string as matching nothing
        return typeof filter.value === 'string'
    }
    return false
}

/** Coerce the stored value (untyped JSON) into clean groups, or null when
 *  absent/malformed — mirroring the backend's read-side fallback, which treats
 *  anything malformed (including the pre-rename `{label, tags}` shape) as
 *  "use the built-in examples". */
export function normalizeTicketGroups(raw: unknown): TicketGroup[] | null {
    if (!Array.isArray(raw) || raw.length === 0) {
        return null
    }
    const groups: TicketGroup[] = []
    for (const entry of raw) {
        const group = (entry ?? {}) as Record<string, unknown>
        if (typeof group.label !== 'string' || !Array.isArray(group.filters)) {
            return null
        }
        if (!group.filters.every((filter) => isStructurallyUsableFilter(filter))) {
            return null
        }
        groups.push({ label: group.label, filters: group.filters.map((filter) => ({ ...filter })) })
    }
    // The backend also treats duplicate labels as malformed (falls back to the
    // examples), so those must read as "not customized" here too.
    if (new Set(groups.map((group) => group.label)).size !== groups.length) {
        return null
    }
    return groups
}

function validateStringListValue(value: string[], label: string): void {
    if (value.length === 0) {
        throw new Error(`A filter in "${label}" has an empty value list — it needs at least one value.`)
    }
    if (value.length > 100) {
        throw new Error(`At most 100 values per filter (a filter in "${label}" has ${value.length}).`)
    }
    for (const item of value) {
        if (!item.trim() || item.trim().length > 200) {
            throw new Error(`Values in "${label}" must be non-empty strings of at most 200 characters.`)
        }
    }
}

function validateFilter(filter: TicketGroupFilter, label: string): void {
    if (filter.type === 'sql') {
        // A sql filter has no operator — just an expression. We can only check
        // that it is present and within length; whether it actually compiles is
        // the server's call, since parsing HogQL client-side isn't possible.
        const expression = typeof filter.expression === 'string' ? filter.expression.trim() : ''
        if (!expression) {
            throw new Error(`The SQL expression filter in "${label}" needs a non-empty expression.`)
        }
        if (expression.length > MAX_SQL_EXPRESSION_LENGTH) {
            throw new Error(
                `The SQL expression in "${label}" is too long (max ${MAX_SQL_EXPRESSION_LENGTH} characters, got ${expression.length}).`
            )
        }
        return
    }
    switch (filter.operator) {
        case 'any_of':
        case 'in':
            validateStringListValue(filter.value, label)
            return
        case 'icontains':
            if (!filter.value.trim() || filter.value.trim().length > 200) {
                throw new Error(
                    `The email_from filter in "${label}" needs a non-empty string of at most 200 characters.`
                )
            }
            return
        case 'is_set':
        case 'is_not_set':
            if ('value' in filter) {
                throw new Error(`The "${filter.operator}" operator in "${label}" takes no value.`)
            }
            return
        case 'date_before':
        case 'date_after':
            // The strict shared date grammar
            if (!isValidDateValue(filter.value.trim())) {
                throw new Error(
                    `Can't parse the date "${filter.value}" in "${label}" — use a relative date like "-3d" ` +
                        '(units h/d/w/m/y, N up to 1000, optional case-sensitive Start/End suffix) or an ISO ' +
                        'datetime like "2026-07-01".'
                )
            }
            return
        default:
            // Unreachable while TicketGroupFilter and the zod union above it stay
            // in step. Only one drift direction is type-checked (a zod variant
            // with no TS variant fails typecheck), so this catches the other:
            // a TS variant added without a case here would silently skip
            // validation entirely.
            throw new Error(
                `A filter in "${label}" has a shape this validator doesn't know — the TicketGroupFilter type and ` +
                    'the zod filter union in schema/tool-inputs.ts have drifted apart; add the missing case.'
            )
    }
}

/** Fail fast on the mistakes the backend serializer would reject anyway, with
 *  messages actionable enough to fix without a round trip. The server stays
 *  the authority — anything it rejects surfaces as the PATCH error. */
export function validateTicketGroups(groups: TicketGroup[]): void {
    if (groups.length > 50) {
        throw new Error(`At most 50 groups are allowed (got ${groups.length}).`)
    }
    // Counted across ALL groups, not per group — same order the backend checks in.
    const sqlFilterCount = groups.reduce(
        (total, group) => total + group.filters.filter((filter) => filter.type === 'sql').length,
        0
    )
    if (sqlFilterCount > MAX_SQL_FILTERS) {
        throw new Error(`At most ${MAX_SQL_FILTERS} SQL expression filters are allowed (${sqlFilterCount} given).`)
    }
    const seenLabels = new Set<string>()
    for (const group of groups) {
        const label = group.label.trim()
        if (!label) {
            throw new Error('Each group needs a non-empty label.')
        }
        if (label.length > 100) {
            throw new Error(`Label too long (max 100 characters): "${label.slice(0, 40)}…"`)
        }
        if (seenLabels.has(label)) {
            throw new Error(`Duplicate group label "${label}" — labels must be unique.`)
        }
        seenLabels.add(label)
        if (group.filters.length > 10) {
            throw new Error(`At most 10 filters per group ("${label}" has ${group.filters.length}).`)
        }
        for (const filter of group.filters) {
            validateFilter(filter, label)
        }
    }
}

function settingsUrl(context: Context, projectId: string): string {
    return `${context.api.getProjectBaseUrl(projectId)}/support/settings#selectedSetting=conversations-ticket-groups`
}

async function readSavedGroups(context: Context, projectId: string): Promise<TicketGroup[] | null> {
    const projectResult = await context.api.projects().get({ projectId })
    if (!projectResult.success) {
        throw new Error(`Failed to read conversations settings: ${projectResult.error.message}`)
    }
    const settings = (projectResult.data as { conversations_settings?: Record<string, unknown> | null })
        .conversations_settings
    return normalizeTicketGroups(settings?.ticket_groups)
}

const describeGroups = (groups: TicketGroup[]): string =>
    groups.map((group, index) => `${index + 1}. ${group.label}`).join(' → ')

export const getTicketGroupsHandler: ToolBase<typeof ConversationsTicketGroupsGetSchema, GetResult>['handler'] = async (
    context: Context,
    _params: GetParams
) => {
    const projectId = await context.stateManager.getProjectId()
    const groups = await readSavedGroups(context, projectId)
    return {
        customized: groups !== null,
        groups,
        message: groups
            ? `The team has ${groups.length} custom ticket group(s): ${describeGroups(groups)}. ` +
              'A ticket takes the first group whose filters ALL match; tickets matching no group rank with the first group.'
            : 'The team has no custom ticket groups saved and follows the built-in example groups. ' +
              'Save groups with conversations-ticket-groups-update to customize.',
        settings_url: settingsUrl(context, projectId),
    }
}

export const updateTicketGroupsHandler: ToolBase<
    typeof ConversationsTicketGroupsUpdateSchema,
    UpdateResult
>['handler'] = async (context: Context, params: UpdateParams) => {
    const projectId = await context.stateManager.getProjectId()

    if (params.groups) {
        validateTicketGroups(params.groups)
    }

    if (!params.confirm) {
        // Only the preview needs the current groups (for an accurate message);
        // a confirmed write PATCHes without the extra read.
        const current = await readSavedGroups(context, projectId)
        const preview = params.groups
            ? `Would replace the team's ticket groups (currently ${
                  current ? `${current.length} group(s)` : 'the built-in examples'
              }) with ${params.groups.length} group(s): ${describeGroups(params.groups)}.`
            : current
              ? 'Would reset the team to the built-in example groups, discarding its custom groups.'
              : 'The team already follows the built-in example groups — saving this would be a no-op.'
        return {
            applied: false,
            groups: params.groups ?? null,
            message: `Preview only — nothing saved. ${preview} Re-run with confirm:true to save.`,
            settings_url: settingsUrl(context, projectId),
        }
    }

    const updateResult = await context.api.projects().updateConversationsTicketGroups({
        projectId,
        groups: params.groups ?? null,
    })
    if (!updateResult.success) {
        throw new Error(`Failed to save ticket groups: ${updateResult.error.message}`)
    }
    const saved = normalizeTicketGroups(
        (updateResult.data as { conversations_settings?: Record<string, unknown> | null }).conversations_settings
            ?.ticket_groups
    )

    return {
        applied: true,
        groups: saved,
        message: saved
            ? `Saved ${saved.length} group(s): ${describeGroups(saved)}. Sorting the tickets list with ` +
              'order_by=ticket_group now uses these groups (group first, then SLA deadline within each group).'
            : 'Reset — the team now follows the built-in example groups.',
        settings_url: settingsUrl(context, projectId),
    }
}

export const getTicketGroupsTool = (): ToolBase<typeof ConversationsTicketGroupsGetSchema, GetResult> => ({
    name: 'conversations-ticket-groups-get',
    schema: ConversationsTicketGroupsGetSchema,
    handler: getTicketGroupsHandler,
})

export const updateTicketGroupsTool = (): ToolBase<typeof ConversationsTicketGroupsUpdateSchema, UpdateResult> => ({
    name: 'conversations-ticket-groups-update',
    schema: ConversationsTicketGroupsUpdateSchema,
    handler: updateTicketGroupsHandler,
})
