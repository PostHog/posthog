import { ApiError } from './client'
import { missingScope } from './scopeErrors'

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
})
