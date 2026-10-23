import { ApiError } from './client'
import { missingFeatureScope, missingScope, missingViewsScope } from './scopeErrors'

describe('missingScope', () => {
    test.each<[string, unknown, string | null]>([
        [
            'a missing scope',
            new ApiError(403, { detail: "API key missing required scope 'dashboard:read'" }),
            'dashboard:read',
        ],
        [
            'a 403 without access',
            new ApiError(403, { detail: 'You do not have permission to perform this action.' }),
            null,
        ],
        ['a 404', new ApiError(404, { detail: "API key missing required scope 'dashboard:read'" }), null],
        ['a plain error', new Error("API key missing required scope 'insight:read'"), null],
    ])('reads %s', (_name, error, expected) => {
        expect(missingScope(error)).toBe(expected)
    })

    test.each<[string, string[] | null, string | null]>([
        ['an unknown grant', null, null],
        ['every scope', ['dashboard:read', 'insight:read', 'file_system_shortcut:write'], null],
        ['write scopes that cover the reads', ['dashboard:write', 'insight:write', 'file_system_shortcut:write'], null],
        ['a grant from before Views', ['user:read', 'query:read'], 'dashboard:read'],
        [
            'a read where write is needed',
            ['dashboard:read', 'insight:read', 'file_system_shortcut:read'],
            'file_system_shortcut:write',
        ],
    ])('finds the missing Views scope in %s', (_name, granted, expected) => {
        expect(missingViewsScope(granted)).toBe(expected)
    })

    test.each<[string, string[], 'errors' | 'replay', string | null]>([
        ['a write that covers the error tracking read', ['error_tracking:write'], 'errors', null],
        ['a grant without the summary scopes', ['session_recording:read'], 'replay', 'replay_scanner:read'],
    ])('finds the missing feature scope in %s', (_name, granted, feature, expected) => {
        expect(missingFeatureScope(granted, feature)).toBe(expected)
    })
})
