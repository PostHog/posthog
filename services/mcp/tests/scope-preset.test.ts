import { describe, expect, it } from 'vitest'

import { MCP_SCOPE_PRESET, resolveScopePreset } from '@/lib/scope-preset'

// Scope sets mirror what `resolve_scopes` in `posthog/temporal/oauth.py` mints for each preset.
// Every server-minted token carries `task:write` and `internal_run:read` (INTERNAL_SCOPES), so
// each set below includes them — the classifier must still tell the presets apart through them.
const INTERNAL_SCOPES = ['task:write', 'internal_run:read']

// A scout token: reads plus its own internal write scope and the narrow user-facing writes.
const SCOUT_SCOPES = [...INTERNAL_SCOPES, 'insight:read', 'signal_scout_internal:write', 'notebook:write']

// A report-research run: read-only base plus the scratchpad write scope, no user-facing writes.
const RESEARCH_SCOPES = [...INTERNAL_SCOPES, 'insight:read', 'dashboard:read', 'signal_scratchpad_internal:write']

// An implementation run: the scratchpad write scope plus user-facing writes.
const IMPLEMENTATION_SCOPES = [
    ...INTERNAL_SCOPES,
    'insight:read',
    'insight:write',
    'dashboard:write',
    'signal_scratchpad_internal:write',
]

// A plain user token: reads (and maybe writes) but none of the internal caller scopes.
const READ_ONLY_USER_SCOPES = [...INTERNAL_SCOPES, 'insight:read', 'dashboard:read']
const FULL_USER_SCOPES = [...INTERNAL_SCOPES, 'insight:read', 'insight:write', 'dashboard:write']

describe('resolveScopePreset', () => {
    it.each([
        ['a scout token', SCOUT_SCOPES, MCP_SCOPE_PRESET.SCOUT],
        ['a research token', RESEARCH_SCOPES, MCP_SCOPE_PRESET.RESEARCH],
        ['an implementation token', IMPLEMENTATION_SCOPES, MCP_SCOPE_PRESET.IMPLEMENTATION],
        ['a read-only user token', READ_ONLY_USER_SCOPES, MCP_SCOPE_PRESET.USER],
        ['a full user token', FULL_USER_SCOPES, MCP_SCOPE_PRESET.USER],
        ['no scopes at all', [], MCP_SCOPE_PRESET.USER],
        ['undefined scopes', undefined, MCP_SCOPE_PRESET.USER],
    ])('classifies %s', (_label, scopes, expected) => {
        expect(resolveScopePreset(scopes)).toBe(expected)
    })

    it('reads as a scout even when the scratchpad write scope is also present', () => {
        expect(resolveScopePreset(['signal_scout_internal:write', 'signal_scratchpad_internal:write'])).toBe(
            MCP_SCOPE_PRESET.SCOUT
        )
    })
})
