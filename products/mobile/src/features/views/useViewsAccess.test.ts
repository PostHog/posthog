import { ApiError } from '@/api/client'
import type { ScopedFeature } from '@/api/scopeErrors'

import {
    featureAccessFor,
    reportScopeError,
    useScopeErrorStore,
    type ViewsAccessInput,
    type ViewsAccessState,
} from './useViewsAccess'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)

const REQUESTED = ['user:read', 'query:read', 'dashboard:read', 'insight:read', 'file_system_shortcut:write']

describe('featureAccessFor', () => {
    test.each<[string, ViewsAccessInput, ViewsAccessState, ScopedFeature?]>([
        [
            'a sign-in that granted every Views scope',
            { method: 'oauth', tokens: { grantedScopes: REQUESTED, requestedScopes: REQUESTED }, reported: null },
            'ok',
        ],
        [
            'a session from before the app asked for the Views scopes',
            { method: 'oauth', tokens: { grantedScopes: ['user:read'], requestedScopes: null }, reported: null },
            'reauth',
        ],
        [
            'a sign-in that asked for a scope the server left out',
            {
                method: 'oauth',
                tokens: { grantedScopes: ['user:read', 'dashboard:read', 'insight:read'], requestedScopes: REQUESTED },
                reported: null,
            },
            'unavailable',
        ],
        [
            'a session whose grant is unknown and a request named a missing scope',
            { method: 'oauth', tokens: { grantedScopes: null, requestedScopes: null }, reported: 'dashboard:read' },
            'reauth',
        ],
        [
            'a personal API key without the scopes',
            { method: 'personal_api_key', tokens: null, reported: 'insight:read' },
            'personal-key-missing-scopes',
        ],
        [
            'a Views grant from before the app asked for the error tracking scopes',
            { method: 'oauth', tokens: { grantedScopes: REQUESTED, requestedScopes: REQUESTED }, reported: null },
            'reauth',
            'errors',
        ],
    ])('%s', (_name, input, expected, feature = 'views') => {
        expect(featureAccessFor(input, feature).state).toBe(expected)
    })

    test('a missing scope reported by one feature leaves the others alone', () => {
        const refused = new ApiError(403, { detail: "API key missing required scope 'error_tracking:read'" })

        expect(reportScopeError(refused, 'errors')).toBe(true)

        expect(useScopeErrorStore.getState().reported).toEqual({
            views: null,
            errors: 'error_tracking:read',
            replay: null,
        })
    })
})
