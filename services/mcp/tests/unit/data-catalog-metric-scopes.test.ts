import { describe, expect, it } from 'vitest'

import { hasScopes } from '@/lib/api'
import { getToolDefinition } from '@/tools/toolDefinitions'

// Tool scopes are all-or-nothing at catalog-filter time (`hasScopes` requires every declared
// scope), while MetricViewSet.dangerously_get_required_scopes only demands insight:read when the
// request supplies source_insight_short_id. Declaring insight:read statically would hide these
// tools from a data_catalog:write-only credential doing an ordinary definition write.
describe('data catalog metric write tools', () => {
    it.each(['data-catalog-metric-create', 'data-catalog-metric-update'])(
        '%s stays visible to a data_catalog:write-only credential',
        (toolName) => {
            const required = getToolDefinition(toolName).required_scopes ?? []

            expect(hasScopes(['data_catalog:write'], required)).toBe(true)
        }
    )
})
