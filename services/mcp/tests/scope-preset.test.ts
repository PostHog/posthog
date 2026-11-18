import { describe, expect, it } from 'vitest'

import { MCP_SCOPE_PRESET, resolveScopePreset } from '@/lib/scope-preset'

// Every server-minted token carries `task:write` and `internal_run:read` (INTERNAL_SCOPES in
// `posthog/temporal/oauth.py`), so each sandbox set below includes them.
const INTERNAL_SCOPES = ['task:write', 'internal_run:read']

// A scout token, as `resolve_scopes` mints for `signals_scout`: reads plus the scout-internal
// write scope and the narrow user-facing writes.
const SCOUT_SCOPES = [...INTERNAL_SCOPES, 'insight:read', 'signal_scout_internal:write', 'notebook:write']

// The two pipeline sets carry `signal_scratchpad_internal:write`, which no preset mints yet.
// They describe the `signals_research` / `signals_implementation` presets the scope-split work
// adds, so these cases pin the classifier's contract ahead of it.
const RESEARCH_SCOPES = [...INTERNAL_SCOPES, 'insight:read', 'dashboard:read', 'signal_scratchpad_internal:write']
const IMPLEMENTATION_SCOPES = [
    ...INTERNAL_SCOPES,
    'insight:read',
    'insight:write',
    'dashboard:write',
    'signal_scratchpad_internal:write',
]

// What `read_only` and `full` mint today for every other sandbox run, the report-research and
// implementation runs included: server-minted, no caller-specific scope.
const READ_ONLY_SANDBOX_SCOPES = [...INTERNAL_SCOPES, 'insight:read', 'dashboard:read']
const FULL_SANDBOX_SCOPES = [...INTERNAL_SCOPES, 'insight:read', 'insight:write', 'dashboard:write']

// A person's own token (personal API key or OAuth consent) never carries `internal_run:read`.
const READ_ONLY_USER_SCOPES = ['insight:read', 'dashboard:read']
const FULL_USER_SCOPES = ['insight:read', 'insight:write', 'dashboard:write', 'task:write']

describe('resolveScopePreset', () => {
    it.each([
        ['a scout token', SCOUT_SCOPES, MCP_SCOPE_PRESET.SCOUT],
        ['a research token', RESEARCH_SCOPES, MCP_SCOPE_PRESET.RESEARCH],
        ['an implementation token', IMPLEMENTATION_SCOPES, MCP_SCOPE_PRESET.IMPLEMENTATION],
        ["a read-only sandbox token (today's research run)", READ_ONLY_SANDBOX_SCOPES, MCP_SCOPE_PRESET.SANDBOX],
        ["a full sandbox token (today's implementation run)", FULL_SANDBOX_SCOPES, MCP_SCOPE_PRESET.SANDBOX],
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
