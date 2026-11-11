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
    beforeEach(() => useScopeErrorStore.getState().clear())

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
        [
            'an inbox session that the server still accepts through task scopes',
            {
                method: 'oauth',
                tokens: { grantedScopes: ['task:write'], requestedScopes: ['task:write'] },
                reported: null,
            },
            'ok',
            'inbox',
        ],
        [
            'a legacy inbox grant rejected after the fallback is removed',
            {
                method: 'oauth',
                tokens: { grantedScopes: ['task:write'], requestedScopes: ['task:write'] },
                reported: 'inbox:read',
            },
            'reauth',
            'inbox',
        ],
        [
            'an inbox scope requested but not granted by the OAuth application',
            {
                method: 'oauth',
                tokens: { grantedScopes: ['task:write'], requestedScopes: ['task:write', 'inbox:read', 'inbox:write'] },
                reported: 'inbox:read',
            },
            'unavailable',
            'inbox',
        ],
        [
            'a personal API key rejected for an inbox scope',
            { method: 'personal_api_key', tokens: null, reported: 'inbox:write' },
            'personal-key-missing-scopes',
            'inbox',
        ],
    ])('%s', (_name, input, expected, feature = 'views') => {
        expect(featureAccessFor(input, feature).state).toBe(expected)
    })

    test.each<[ScopedFeature, string, boolean]>([
        ['errors', 'error_tracking:read', true],
        ['inbox', 'inbox:read', true],
        ['inbox', 'today:read', false],
    ])('a missing %s scope %s leaves other features alone', (feature, scope, handled) => {
        const refused = new ApiError(403, { detail: `API key missing required scope '${scope}'` })

        expect(reportScopeError(refused, feature)).toBe(handled)

        expect(useScopeErrorStore.getState().reported).toEqual({
            views: null,
            errors: null,
            replay: null,
            inbox: null,
            ...(handled ? { [feature]: scope } : {}),
        })
    })
})
