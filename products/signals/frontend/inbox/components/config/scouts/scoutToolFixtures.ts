import type { ScoutToolCatalogueApi, ScoutToolCatalogueEntryApi } from 'products/signals/frontend/generated/api.schemas'

function tool(
    name: string,
    title: string,
    category: string,
    overrides: Partial<ScoutToolCatalogueEntryApi> = {}
): ScoutToolCatalogueEntryApi {
    return {
        name,
        title,
        summary: `${title} in this project.`,
        category,
        feature: category.toLowerCase().replace(/ /g, '_'),
        required_scopes: [],
        is_read_only: true,
        requires_ai_consent: false,
        holdable: true,
        missing_scopes: [],
        feature_flag: null,
        feature_flag_behavior: null,
        feature_flag_variant: null,
        hidden_when_flag_on: null,
        feature_entitlement: null,
        ...overrides,
    }
}

/** A small catalogue with read, write, unavailable, and run context tools, for tests and stories. */
export const SCOUT_TOOL_CATALOGUE: ScoutToolCatalogueApi = {
    tools: [
        tool('skill-get', 'Get skill', 'Skills'),
        tool('skill-file-get', 'Get skill file', 'Skills'),
        tool('dashboard-get', 'Get dashboard', 'Dashboards', { required_scopes: ['dashboard:read'] }),
        tool('dashboard-update', 'Update dashboard', 'Dashboards', {
            required_scopes: ['dashboard:write'],
            is_read_only: false,
            missing_scopes: ['dashboard:write'],
        }),
        tool('insight-get', 'Get insight', 'Product analytics', { required_scopes: ['insight:read'] }),
        tool('insight-create', 'Create insight', 'Product analytics', {
            required_scopes: ['insight:write', 'query:read'],
            is_read_only: false,
            missing_scopes: ['insight:write'],
        }),
        tool('conversations-tickets-notes-create', 'Add a private ticket note', 'Support', {
            required_scopes: ['ticket:write'],
            is_read_only: false,
        }),
        tool('feature-flag-delete', 'Delete feature flag', 'Feature flags', {
            required_scopes: ['feature_flag:write'],
            is_read_only: false,
            holdable: false,
            missing_scopes: ['feature_flag:write'],
        }),
        tool('scout-emit-report', 'Emit report', 'Scouts'),
        tool('scout-notes-list', 'List scout notes', 'Scouts'),
    ],
    tool_presets: [
        { name: 'read_only', label: 'Read only', tools: ['dashboard-get', 'insight-get'] },
        {
            name: 'support_notes',
            label: 'Support notes',
            tools: ['conversations-tickets-notes-create', 'dashboard-get', 'insight-get'],
        },
    ],
    presets: [],
    run_context_tools: ['scout-emit-report', 'scout-notes-list', 'skill-get', 'skill-file-get'],
    grantable_write_scopes: ['dashboard:write', 'insight:write'],
}
