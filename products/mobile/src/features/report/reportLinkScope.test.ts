import { useAuthStore } from '@/auth/authStore'

import {
    followLinkProject,
    type ReportLink,
    type ReportLinkScope,
    reportLinkFromParams,
    reportLinkScope,
} from './reportLinkScope'

jest.mock('@/demo/demoMode', () => ({ useDataMode: () => 'live' }))

const SESSION = { host: 'https://us.posthog.com', projectId: 2 }

describe('reportLinkScope', () => {
    test.each<[string, ReportLink, typeof SESSION | null, ReportLinkScope]>([
        ['no link scope', { projectId: null, host: null }, SESSION, { kind: 'scope', override: null }],
        ['the session project', { projectId: 2, host: 'us.posthog.com' }, SESSION, { kind: 'scope', override: null }],
        [
            'another project in the same region',
            { projectId: 7, host: 'us.posthog.com' },
            SESSION,
            { kind: 'scope', override: { host: 'https://us.posthog.com', projectId: 7 } },
        ],
        [
            'another project with no host',
            { projectId: 7, host: null },
            SESSION,
            { kind: 'scope', override: { host: 'https://us.posthog.com', projectId: 7 } },
        ],
        ['another region', { projectId: 2, host: 'eu.posthog.com' }, SESSION, { kind: 'elsewhere' }],
        ['a signed-out session', { projectId: 7, host: 'eu.posthog.com' }, null, { kind: 'scope', override: null }],
    ])('%s', (_, link, session, expected) => {
        expect(reportLinkScope(link, session)).toEqual(expected)
    })

    test.each<[string, Record<string, string | string[] | undefined>, ReportLink]>([
        ['a web link', { project: '7', host: 'US.posthog.com' }, { projectId: 7, host: 'us.posthog.com' }],
        ['no link', {}, { projectId: null, host: null }],
        [
            'a repeated parameter',
            { project: ['7', '8'], host: ['us.posthog.com', 'eu.posthog.com'] },
            { projectId: null, host: null },
        ],
        ['a project that is not a number', { project: '7abc', host: '' }, { projectId: null, host: null }],
    ])('reads %s from the route', (_, params, expected) => {
        expect(reportLinkFromParams(params)).toEqual(expected)
    })

    test.each<[string, number | null | undefined, boolean, number]>([
        ['a project the account lists', 7, true, 7],
        ['a project the cached account does not list', 8, false, 2],
        ['a link without a project', undefined, true, 2],
    ])('follows %s', (_, projectId, followed, expected) => {
        useAuthStore.setState({
            projectId: 2,
            projects: [
                { id: 2, name: 'Session', organizationId: 'org-1', organizationName: 'Example' },
                { id: 7, name: 'Linked', organizationId: 'org-1', organizationName: 'Example' },
            ],
        })
        expect(followLinkProject(projectId)).toBe(followed)
        expect(useAuthStore.getState().projectId).toBe(expected)
    })
})
