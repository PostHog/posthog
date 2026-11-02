import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'

import { fetchOrganization } from '@/api/users'
import { useAuthStore } from '@/auth/authStore'
import { useDemoMode } from '@/demo/demoMode'
import { cancelAiApproval, checkAiApproval, useAiApprovalStore } from '@/features/ai/aiApproval'
import { aiConsentKey, useAiConsentStore, waitForAiConsent } from '@/features/chat/aiConsentStore'

import { deliverPermissionResponse } from './commands'
import { handoffEntry, useHandoffStore } from './handoffStore'
import { useDecisionAnswer, useHandoffActions } from './hooks'
import { currentDecision } from './liveReport'
import { parsePermissionRequest, requestKind } from './permissionRequest'
import { initialRunState } from './runStream'

jest.mock('@/api/users', () => ({ fetchOrganization: jest.fn() }))
jest.mock('./commands', () => ({ ...jest.requireActual('./commands'), deliverPermissionResponse: jest.fn() }))

const HOST = 'https://app.example.com'
const REPORT = 'report-1'

function setRun(runId = 'run-1', requestId = 'request-1'): void {
    const record = parsePermissionRequest({
        requestId,
        options: [{ optionId: 'allow', kind: 'allow_once', name: 'Yes' }],
        toolCall: { toolCallId: 'tool-1', title: 'Edit example.ts', _meta: { claudeCode: { toolName: 'Edit' } } },
    })
    if (!record) throw new Error('Invalid fixture')
    useHandoffStore.setState({
        reports: {
            [REPORT]: {
                refresh: 0,
                live: {
                    ...initialRunState('task-1', runId, 'in_progress'),
                    pending: { record, kind: requestKind(record), replayed: false },
                },
            },
        },
    })
}

function setup(): {
    result: ReturnType<typeof renderHook<ReturnType<typeof useHandoffActions>, unknown>>['result']
    unmount: () => void
    clear: () => void
} {
    const client = new QueryClient()
    const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    const hook = renderHook(() => useHandoffActions(REPORT), { wrapper })
    return { result: hook.result, unmount: hook.unmount, clear: () => client.clear() }
}

beforeEach(async () => {
    await waitForAiConsent()
    useDemoMode.setState({ enabled: false })
    useAiConsentStore.getState().clear()
    useAuthStore.setState({
        status: 'signed_in',
        signedIn: true,
        host: HOST,
        projectId: 7,
        user: { uuid: 'person-1', distinctId: 'distinct-1', email: 'person@example.com', name: 'Person' },
        organizations: [{ id: 'org-1', name: 'Example', aiDataProcessingApproved: true, membershipLevel: 1 }],
        projects: [{ id: 7, name: 'Project', organizationId: 'org-1', organizationName: 'Example' }],
    })
    jest.mocked(fetchOrganization).mockResolvedValue({
        id: 'org-1',
        name: 'Example',
        teams: [{ id: 7, name: 'Project' }],
        is_ai_data_processing_approved: true,
        membership_level: 1,
    })
    jest.mocked(deliverPermissionResponse).mockReset()
    setRun()
})
afterEach(() => {
    cancelAiApproval()
    useAiConsentStore.getState().clear()
    useHandoffStore.setState({ reports: {} })
})

test.each(['run', 'question', 'project'] as const)(
    'an answer is not delivered when the %s changes during approval',
    async (change) => {
        const hook = setup()
        const question = currentDecision(handoffEntry(REPORT))
        if (!question) throw new Error('Missing question')
        let sending: Promise<void> = Promise.resolve()
        act(() => {
            sending = hook.result.current.answerDecision.run({
                questionId: question.id,
                optionId: 'allow',
                text: 'Yes',
            })
        })
        await waitFor(() => expect(useAiApprovalStore.getState().request?.access?.kind).toBe('needs_consent'))
        await act(async () => {
            if (change === 'project') useAuthStore.setState({ projectId: 8 })
            else setRun(change === 'run' ? 'run-2' : 'run-1', change === 'question' ? 'request-2' : 'request-1')
            await checkAiApproval(true)
            await sending
        })
        expect(deliverPermissionResponse).not.toHaveBeenCalled()
        hook.unmount()
        hook.clear()
    }
)

test('leaving the screen aborts an approved decision delivery', async () => {
    useAiConsentStore.getState().accept(aiConsentKey(HOST, 'person-1'))
    let signal: AbortSignal | undefined
    jest.mocked(deliverPermissionResponse).mockImplementation((_run, _params, options) => {
        signal = options?.signal
        return new Promise((_resolve, reject) => {
            signal?.addEventListener('abort', () => reject(new Error('Aborted')))
        })
    })
    const hook = setup()
    const question = currentDecision(handoffEntry(REPORT))
    if (!question) throw new Error('Missing question')
    let sending: Promise<void> = Promise.resolve()
    act(() => {
        sending = hook.result.current.answerDecision.run({ questionId: question.id, optionId: 'allow', text: 'Yes' })
    })
    await waitFor(() => expect(deliverPermissionResponse).toHaveBeenCalledTimes(1))
    const answer = renderHook(() => useDecisionAnswer(REPORT))
    expect(answer.result.current?.canUndo).toBe(false)
    await act(async () => {
        await hook.result.current.undoDecision.run()
    })
    expect(signal?.aborted).toBe(false)
    expect(handoffEntry(REPORT).answer?.delivery).toBe('sending')
    answer.unmount()
    hook.unmount()
    await act(async () => {
        await sending
    })
    expect(signal?.aborted).toBe(true)
    hook.clear()
})
