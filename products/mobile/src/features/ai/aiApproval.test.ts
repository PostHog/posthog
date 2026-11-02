import { act, renderHook, waitFor } from '@testing-library/react-native'

import { fetchOrganization, type OrganizationApi } from '@/api/users'
import { useAuthStore } from '@/auth/authStore'
import { useDemoMode } from '@/demo/demoMode'
import { aiConsentKey, useAiConsentStore, waitForAiConsent } from '@/features/chat/aiConsentStore'

import { cancelAiApproval, checkAiApproval, requestAiApproval, useAiApproval, useAiApprovalStore } from './aiApproval'

jest.mock('@/api/users', () => ({ fetchOrganization: jest.fn() }))

const HOST = 'https://app.example.com'
const USER = { id: 1, uuid: 'person-1', distinctId: 'distinct-1', email: 'person@example.com', name: 'Person' }
const ORG: OrganizationApi = {
    id: 'org-1',
    name: 'Example',
    teams: [{ id: 7, name: 'Project' }],
    is_ai_data_processing_approved: true,
    membership_level: 1,
}
const fetchOrg = jest.mocked(fetchOrganization)

beforeEach(async () => {
    await waitForAiConsent()
    useDemoMode.setState({ enabled: false })
    useAiConsentStore.getState().clear()
    useAuthStore.setState({
        status: 'signed_in',
        signedIn: true,
        host: HOST,
        user: USER,
        projectId: 7,
        accountError: null,
        organizations: [{ id: ORG.id, name: ORG.name, aiDataProcessingApproved: true, membershipLevel: 1 }],
        projects: [{ id: 7, name: 'Project', organizationId: ORG.id, organizationName: ORG.name }],
    })
    fetchOrg.mockReset().mockResolvedValue(ORG)
})
afterEach(cancelAiApproval)

async function shown(kind: string): Promise<void> {
    await waitFor(() => expect(useAiApprovalStore.getState().request?.access?.kind).toBe(kind))
}

test.each(['chat', 'handoff', 'replay'] as const)(
    '%s waits for individual approval, then rechecks organization approval',
    async (action) => {
        const result = requestAiApproval(action)
        await shown('needs_consent')
        expect(useAiConsentStore.getState().accepted).toEqual({})
        await checkAiApproval(true)
        await expect(result).resolves.toBe(true)
        expect(fetchOrg).toHaveBeenCalledTimes(2)
        expect(useAiConsentStore.getState().accepted[aiConsentKey(HOST, USER.uuid)]).toBe(true)
    }
)

test.each([1, 8, 15, null, undefined] as const)(
    'only confirmed admins and owners get organization settings (%s)',
    async (membership) => {
        fetchOrg.mockResolvedValue({ ...ORG, membership_level: membership, is_ai_data_processing_approved: false })
        const result = requestAiApproval('handoff')
        await shown('org_blocked')
        const privileged = membership === 8 || membership === 15
        expect(useAiApprovalStore.getState().request?.access).toMatchObject({
            canApprove: privileged,
            settingsUrl: privileged ? `${HOST}/project/7/settings/organization-details#organization-ai-consent` : null,
        })
        cancelAiApproval()
        await expect(result).resolves.toBe(false)
    }
)

test('freshly revoked approval blocks even with cached approval and individual consent', async () => {
    useAiConsentStore.getState().accept(aiConsentKey(HOST, USER.uuid))
    fetchOrg.mockResolvedValue({ ...ORG, is_ai_data_processing_approved: false })
    const result = requestAiApproval('chat')
    await shown('org_blocked')
    cancelAiApproval()
    await expect(result).resolves.toBe(false)
})

test.each(['failed', 'unknown', 'removed_project'] as const)(
    'cannot use cached approval after %s fresh verification',
    async (scenario) => {
        useAiConsentStore.getState().accept(aiConsentKey(HOST, USER.uuid))
        if (scenario === 'failed') fetchOrg.mockRejectedValue(new Error('Offline'))
        if (scenario === 'unknown') fetchOrg.mockResolvedValue({ ...ORG, is_ai_data_processing_approved: undefined })
        if (scenario === 'removed_project') fetchOrg.mockResolvedValue({ ...ORG, teams: [] })
        const result = requestAiApproval('replay')
        await shown('org_unknown')
        cancelAiApproval()
        await expect(result).resolves.toBe(false)
    }
)

test.each(['project', 'user', 'host', 'signed_out'] as const)(
    'changing %s cancels the pending action without approving the new account',
    async (change) => {
        const result = requestAiApproval('handoff')
        await shown('needs_consent')
        if (change === 'project') useAuthStore.setState({ projectId: 8 })
        if (change === 'user') useAuthStore.setState({ user: { ...USER, uuid: 'person-2' } })
        if (change === 'host') useAuthStore.setState({ host: 'https://eu.example.com' })
        if (change === 'signed_out') useAuthStore.setState({ status: 'signed_out' })
        await checkAiApproval(true)
        await expect(result).resolves.toBe(false)
        expect(useAiConsentStore.getState().accepted).toEqual({})
        expect(useAiApprovalStore.getState().request).toBeNull()
    }
)

test('revocation while the disclosure is open cannot be accepted', async () => {
    const result = requestAiApproval('handoff')
    await shown('needs_consent')
    fetchOrg.mockResolvedValue({ ...ORG, is_ai_data_processing_approved: false })
    await checkAiApproval(true)
    await shown('org_blocked')
    expect(useAiConsentStore.getState().accepted).toEqual({})
    cancelAiApproval()
    await expect(result).resolves.toBe(false)
})

test('aborting an action cancels it even while its organization read is pending', async () => {
    let resolveRead!: (organization: OrganizationApi) => void
    fetchOrg.mockImplementation(
        () =>
            new Promise((resolve) => {
                resolveRead = resolve
            })
    )
    const controller = new AbortController()
    const result = requestAiApproval('chat', controller.signal)
    controller.abort()
    await expect(result).resolves.toBe(false)
    resolveRead(ORG)
    await Promise.resolve()
    expect(useAiApprovalStore.getState().request).toBeNull()
})

test('demo actions require no consent or network request', async () => {
    useDemoMode.setState({ enabled: true })
    await expect(requestAiApproval('replay')).resolves.toBe(true)
    expect(fetchOrg).not.toHaveBeenCalled()
})

test.each(['unmount', 'context'] as const)(
    'leaving the originating screen cancels disclosure on %s',
    async (change) => {
        const { result, unmount, rerender } = renderHook(
            ({ context }: { context: string }) => useAiApproval('handoff', context),
            {
                initialProps: { context: 'report-1' },
            }
        )
        let outcome: Promise<boolean> = Promise.resolve(true)
        act(() => {
            outcome = result.current.request()
        })
        await shown('needs_consent')
        if (change === 'unmount') unmount()
        else rerender({ context: 'report-2' })
        await act(async () => {
            await expect(outcome).resolves.toBe(false)
        })
        expect(useAiApprovalStore.getState().request).toBeNull()
        expect(useAiConsentStore.getState().accepted).toEqual({})
    }
)
