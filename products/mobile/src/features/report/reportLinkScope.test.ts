import { act, renderHook } from '@testing-library/react-native'

import { useAuthStore } from '@/auth/authStore'

import { type ReportLink, type ReportLinkScope, reportLinkScope, useReportLinkScope } from './reportLinkScope'

jest.mock('@/demo/demoMode', () => ({ useDataMode: () => 'live' }))
jest.mock('@/lib/analytics', () => ({ track: jest.fn() }))

const PROJECTS = [
    { id: 2, name: 'Web', organizationId: 'org', organizationName: 'Org' },
    { id: 7, name: 'App', organizationId: 'org', organizationName: 'Org' },
]
type Auth = Parameters<typeof reportLinkScope>[1]

const AUTH: Auth = {
    status: 'signed_in',
    host: 'https://us.posthog.com',
    projectId: 2,
    projects: PROJECTS,
    accountLoading: false,
    accountError: null,
}

describe('reportLinkScope', () => {
    test.each<[string, ReportLink, Partial<Auth> | undefined, ReportLinkScope]>([
        ['no link scope', { projectId: null, host: null }, undefined, 'ready'],
        ['the current project', { projectId: 2, host: 'us.posthog.com' }, undefined, 'ready'],
        ['another project of the account', { projectId: 7, host: 'us.posthog.com' }, undefined, 'pending'],
        ['a project the account lacks', { projectId: 9, host: 'us.posthog.com' }, undefined, 'elsewhere'],
        ['a project while the account reloads', { projectId: 9, host: null }, { accountLoading: true }, 'pending'],
        [
            'a project the account could not refresh',
            { projectId: 9, host: null },
            { accountError: 'Offline' },
            'unverified',
        ],
        ['another region', { projectId: 2, host: 'eu.posthog.com' }, undefined, 'elsewhere'],
        ['a signed-out session', { projectId: 9, host: 'eu.posthog.com' }, { status: 'signed_out' }, 'ready'],
    ])('%s', (_, link, auth, expected) => {
        expect(reportLinkScope(link, { ...AUTH, ...auth })).toBe(expected)
    })

    test('switches to the link project once, and keeps the report there after a manual switch', () => {
        useAuthStore.setState(AUTH)
        const { result, rerender } = renderHook(() => useReportLinkScope({ projectId: 7, host: 'us.posthog.com' }))
        expect(useAuthStore.getState().projectId).toBe(7)
        expect(result.current).toBe('ready')
        act(() => useAuthStore.getState().selectProject(2, 'nav_menu'))
        rerender({})
        expect(useAuthStore.getState().projectId).toBe(2)
        expect(result.current).toBe('ready')
    })

    test('opens the report once a failed account reload brings its project back', () => {
        useAuthStore.setState({ ...AUTH, projects: PROJECTS.slice(0, 1), accountError: 'Offline' })
        const { result, rerender } = renderHook(() => useReportLinkScope({ projectId: 7, host: 'us.posthog.com' }))
        expect(result.current).toBe('unverified')
        act(() => useAuthStore.setState({ projects: PROJECTS, accountError: null }))
        rerender({})
        expect(useAuthStore.getState().projectId).toBe(7)
        expect(result.current).toBe('ready')
    })

    test('keeps the browser offer after a re-render', () => {
        useAuthStore.setState(AUTH)
        const { result, rerender } = renderHook(() => useReportLinkScope({ projectId: 2, host: 'eu.posthog.com' }))
        expect(result.current).toBe('elsewhere')
        act(() => useAuthStore.setState({ accountLoading: true }))
        rerender({})
        expect(result.current).toBe('elsewhere')
    })

    test('drops the browser offer once the screen opens a report of its own project', () => {
        useAuthStore.setState(AUTH)
        const { result, rerender } = renderHook((link: ReportLink) => useReportLinkScope(link), {
            initialProps: { projectId: 2, host: 'eu.posthog.com' },
        })
        expect(result.current).toBe('elsewhere')
        rerender({ projectId: null, host: null })
        expect(result.current).toBe('ready')
    })
})
