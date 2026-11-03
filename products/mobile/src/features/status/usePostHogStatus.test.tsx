import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react-native'
import type { PropsWithChildren, ReactElement } from 'react'

import { useDataMode } from '@/demo/demoMode'

import { regionalStatus, usePostHogStatus } from './usePostHogStatus'

jest.mock('@/demo/demoMode', () => ({ useDataMode: jest.fn(() => 'live') }))

const euAI = { name: 'PostHog AI', group_name: 'EU Cloud 🇪🇺' }
const usAPI = { name: 'API', group_name: 'US Cloud 🇺🇸' }
const incident = { id: 'incident-123', name: 'Elevated error rate', affected_components: [euAI, usAPI] }
const summary = { ongoing_incidents: [incident], in_progress_maintenances: [] }

test('shows a cross-region incident in both menus but only in the affected AI chat', () => {
    expect(regionalStatus(summary, 'us')).toEqual({
        pageUrl: 'https://www.posthogstatus.com/us',
        summary: incident.name,
    })
    expect(regionalStatus(summary, 'eu').aiIncident).toEqual({
        title: incident.name,
        url: 'https://www.posthogstatus.com/incidents/incident-123',
    })
})

test('global incidents and maintenance appear in the menu without implying AI is affected', () => {
    const global = { ...incident, affected_components: [] }
    const maintenance = { name: 'Database maintenance', affected_components: [euAI] }
    const events = { ongoing_incidents: [global], in_progress_maintenances: [maintenance] }
    expect(regionalStatus(events, 'us').summary).toBe(global.name)
    expect(regionalStatus(events, 'eu').aiIncident).toBeUndefined()
    const resolved = { ...events, ongoing_incidents: [] }
    expect(regionalStatus(resolved, 'us').summary).toBeUndefined()
    expect(regionalStatus(resolved, 'eu').summary).toBe(maintenance.name)
    expect(regionalStatus(resolved, 'eu').aiIncident).toBeUndefined()
})

test('clears a resolved AI incident and skips status requests in demo and self-hosted sessions', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const fetchStatus = jest.spyOn(global, 'fetch').mockResolvedValue(Response.json(summary))
    function wrapper({ children }: PropsWithChildren): ReactElement {
        return <QueryClientProvider client={client}>{children}</QueryClientProvider>
    }
    const hook = renderHook((host: string) => usePostHogStatus(host), {
        initialProps: 'https://eu.posthog.com',
        wrapper,
    })
    try {
        await waitFor(() => expect(hook.result.current.aiIncident?.title).toBe(incident.name))
        fetchStatus.mockResolvedValue(Response.json({ ongoing_incidents: [], in_progress_maintenances: [] }))
        await act(() => client.invalidateQueries({ queryKey: ['posthog-status'] }))
        await waitFor(() => expect(hook.result.current.aiIncident).toBeUndefined())
        fetchStatus.mockClear()
        hook.rerender('https://self-hosted.example.com')
        expect(hook.result.current).toEqual({ pageUrl: 'https://www.posthogstatus.com' })
        jest.mocked(useDataMode).mockReturnValue('demo')
        hook.rerender('https://eu.posthog.com')
        expect(hook.result.current).toEqual({ pageUrl: 'https://www.posthogstatus.com' })
        expect(fetchStatus).not.toHaveBeenCalled()
    } finally {
        hook.unmount()
        client.clear()
        fetchStatus.mockRestore()
        jest.mocked(useDataMode).mockReturnValue('live')
    }
})
