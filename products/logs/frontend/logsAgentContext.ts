import { DateRange, LogsQuery } from '~/queries/schema/schema-general'
import {
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    UniversalFiltersGroup,
    UniversalFiltersGroupValue,
} from '~/types'

import { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

import { LogsViewerFilters } from './components/LogsViewer/config/types'
import {
    DEFAULT_DATE_RANGE,
    foldLegacyColumnFilters,
    isValidSeverityLevel,
} from './components/LogsViewer/Filters/logsViewerFiltersLogic'
import { INVESTIGATING_LOGS_SKILL, LOGS_MCP_TOOLS } from './generated/agentContext'

// Each visible chip and the hidden payload items it stands for share a dismiss group, so closing
// the chip actually detaches the payload instead of only hiding the chip.
const SKILL_DISMISS_GROUP = 'logs-scene-skill'
const VIEWER_STATE_DISMISS_GROUP = 'logs-scene-viewer-state'

// All static strings below are build-time constants from our own repo (skill markdown + tool
// descriptions), which is what makes them safe to attach as trusted `instructions` items.
const PREAMBLE_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: SKILL_DISMISS_GROUP,
    value:
        'The user has the PostHog logs viewer open. The full investigating-logs skill and the complete ' +
        'logs MCP tool catalog are included in this context - you already have everything needed to act. ' +
        'Do not spend turns discovering tools or reading skill files: call the listed tools directly, and use ' +
        'the exec `info <tool>` command only when you need a full input schema.',
}

const SKILL_CONTENT_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: SKILL_DISMISS_GROUP,
    value: `Skill ${INVESTIGATING_LOGS_SKILL.name} (embedded): ${INVESTIGATING_LOGS_SKILL.content}`,
}

const TOOL_CONTEXT_ITEMS: AttachedContextItem[] = LOGS_MCP_TOOLS.map((tool) => ({
    type: 'instructions',
    hidden: true,
    dismissGroup: SKILL_DISMISS_GROUP,
    value: `MCP tool ${tool.name}: ${tool.description}`,
}))

const SKILL_CHIP_CONTEXT_ITEM: AttachedContextItem = {
    type: 'skill',
    key: INVESTIGATING_LOGS_SKILL.name,
    label: 'Investigating logs skill',
    dismissGroup: SKILL_DISMISS_GROUP,
}

// Static: names the field the live state carries, so no user-entered filter value reaches trusted
// context. The viewer-state item's value changes with the filters, so it always re-sends.
const APPLY_BACK_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: VIEWER_STATE_DISMISS_GROUP,
    value:
        'The logs_viewer_state item is the current filter state of the open logs viewer (date range, ' +
        'search term, and filter group with severity and service selections folded in as chips). When you ' +
        'call query-logs, the query filters (serviceNames, severityLevels, searchTerm, filterGroup, ' +
        'dateRange) are also applied to the open viewer, so the user sees matching logs both in this chat ' +
        'and on screen. Read logs_viewer_state to see what the user is already filtering on.',
}

export const LOGS_AGENT_HEADLINES: string[] = [
    'How can I help you investigate these logs?',
    'What are you trying to find in the logs?',
]

// The viewer filter state the agent cannot fetch: what the user is currently filtering on. Small by
// construction (a date range, a search term, and a filter group), so it rides along whole with no
// budgeting. It is an untrusted item, so user-typed search terms and values stay intact.
function serializeViewerState(filters: LogsViewerFilters): string {
    return JSON.stringify({
        dateRange: filters.dateRange,
        searchTerm: filters.searchTerm ?? '',
        filterGroup: filters.filterGroup,
    })
}

/**
 * The default agent context for the logs viewer: the embedded investigating-logs skill, the logs MCP
 * tool catalog, an instruction that query-logs calls reflect onto the open page, and the live viewer
 * filter state so the agent can read what the user is filtering on without a fetch.
 */
export function buildLogsAgentContext(filters: LogsViewerFilters): AttachedContextItem[] {
    return [
        PREAMBLE_CONTEXT_ITEM,
        SKILL_CHIP_CONTEXT_ITEM,
        SKILL_CONTENT_CONTEXT_ITEM,
        ...TOOL_CONTEXT_ITEMS,
        APPLY_BACK_CONTEXT_ITEM,
        {
            type: 'logs_viewer_state',
            hidden: true,
            dismissGroup: VIEWER_STATE_DISMISS_GROUP,
            value: serializeViewerState(filters),
        },
    ]
}

function asStringArray(value: unknown): string[] {
    return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : []
}

/**
 * Map a query-logs tool input onto the viewer's filter fields, mirroring what the tool queried onto
 * the open page. The args are raw agent-sent JSON (never zod-validated), so every field is coerced
 * and defaulted. Severity and service selections are folded into the filter group the same way the
 * viewer keeps them, and an omitted field resets that facet so the page shows the query's results
 * exactly - the same complete-query semantics the tool ran with.
 */
export function logsQueryToViewerFilters(input: Record<string, unknown>): Partial<LogsViewerFilters> {
    // All query-logs params are nested inside `query`; fall back to the raw input defensively.
    const query = (input.query && typeof input.query === 'object' ? input.query : input) as Record<string, unknown>

    const flatValues: UniversalFiltersGroup['values'] = (Array.isArray(query.filterGroup) ? query.filterGroup : []).map(
        (filter) => {
            const f = filter as Record<string, unknown>
            return {
                ...f,
                type: (f.type as PropertyFilterType) || PropertyFilterType.LogAttribute,
                operator: (f.operator as PropertyOperator) || PropertyOperator.Exact,
            } as UniversalFiltersGroupValue
        }
    )

    const baseGroup: UniversalFiltersGroup = {
        type: FilterLogicalOperator.And,
        values: [{ type: FilterLogicalOperator.And, values: flatValues }],
    }

    const severityLevels = asStringArray(query.severityLevels).filter(isValidSeverityLevel)
    const serviceNames = asStringArray(query.serviceNames)

    // No `filterGroup` key in the folded-in fields, so empty arrays clear that facet rather than
    // being treated as a no-op against an authoritative group.
    const filterGroup = foldLegacyColumnFilters(baseGroup, {
        severityLevels: severityLevels as LogsQuery['severityLevels'],
        serviceNames: serviceNames as LogsQuery['serviceNames'],
    })

    return {
        dateRange: (query.dateRange as DateRange) ?? DEFAULT_DATE_RANGE,
        searchTerm: typeof query.searchTerm === 'string' ? query.searchTerm : '',
        filterGroup,
    }
}
