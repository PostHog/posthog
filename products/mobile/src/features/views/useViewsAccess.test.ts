import { type ViewsAccessInput, type ViewsAccessState, viewsAccessFor } from './useViewsAccess'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)

const REQUESTED = ['user:read', 'query:read', 'dashboard:read', 'insight:read', 'file_system_shortcut:write']

describe('viewsAccessFor', () => {
    test.each<[string, ViewsAccessInput, ViewsAccessState]>([
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
    ])('%s', (_name, input, expected) => {
        expect(viewsAccessFor(input).state).toBe(expected)
    })
})
