import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'

import { type ExperimentApi, experimentKeys } from '@/api/experiments'
import { setSessionTokens } from '@/auth/tokens'

import {
    useArchiveAction,
    useEditConclusionAction,
    useFinishAction,
    useLaunchAction,
    usePauseResumeAction,
} from './actionHooks'

const mockScope = { host: 'https://app.example.com', projectId: 2 }
const mockSource = {
    fetchExperiment: jest.fn(),
    shipVariant: jest.fn(),
    endExperiment: jest.fn(),
    pauseExperiment: jest.fn(),
    resumeExperiment: jest.fn(),
    launchExperiment: jest.fn(),
    archiveExperiment: jest.fn(),
    updateExperiment: jest.fn(),
}
jest.mock('./hooks', () => ({ useExperimentsContext: () => ({ scope: mockScope, source: mockSource }) }))
jest.mock('@/lib/analytics', () => ({ track: jest.fn() }))

const RUNNING = {
    id: 7,
    name: 'Example experiment',
    status: 'running',
    start_date: '2026-11-01T00:00:00Z',
    feature_flag: { active: true },
} as ExperimentApi
const FINISHED = { ...RUNNING, status: 'stopped', end_date: '2026-11-12T00:00:00Z' } as ExperimentApi
const key = experimentKeys.detail(mockScope, 7)

function setup() {
    const client = new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } },
    })
    const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    const hook = renderHook(
        () => ({
            detail: useQuery({ queryKey: key, queryFn: mockSource.fetchExperiment, initialData: RUNNING }),
            finish: useFinishAction('7'),
            pause: usePauseResumeAction('7'),
            launch: useLaunchAction('7'),
            archive: useArchiveAction('7'),
            conclusion: useEditConclusionAction('7'),
        }),
        { wrapper }
    )
    return { ...hook, client }
}

describe('experiment actions', () => {
    beforeEach(() => {
        for (const mock of Object.values(mockSource)) mock.mockReset()
        mockSource.fetchExperiment.mockResolvedValue(RUNNING)
    })

    it('sends a later end only after an earlier pause answers, so the end is what stays', async () => {
        const { result, client, unmount } = setup()
        let completePause!: (value: ExperimentApi) => void
        mockSource.pauseExperiment.mockImplementationOnce(
            () =>
                new Promise<ExperimentApi>((resolve) => {
                    completePause = resolve
                })
        )
        mockSource.endExperiment.mockResolvedValue(FINISHED)
        let pause!: Promise<void>
        let end!: Promise<void>
        act(() => {
            pause = result.current.pause.run('pause', jest.fn())
        })
        act(() => {
            end = result.current.finish.run({
                request: { kind: 'end', body: { conclusion: 'won', open_cleanup_pr: false } },
                preset: 'end',
                onFinished: jest.fn(),
                onNeedsApproval: jest.fn(),
            })
        })
        await waitFor(() => expect(mockSource.pauseExperiment).toHaveBeenCalled())
        expect(mockSource.endExperiment).not.toHaveBeenCalled()
        await act(async () => {
            completePause({ ...RUNNING, status: 'paused' } as ExperimentApi)
            await pause
            await end
        })
        expect(client.getQueryData(key)).toEqual(FINISHED)
        unmount()
        client.clear()
    })

    it.each(['ship', 'end'] as const)(
        'keeps the completed experiment when an older read finishes after %s',
        async (kind) => {
            const { result, client, unmount } = setup()
            let completeRead!: (value: ExperimentApi) => void
            mockSource.fetchExperiment.mockImplementationOnce(
                () =>
                    new Promise<ExperimentApi>((resolve) => {
                        completeRead = resolve
                    })
            )
            let read!: Promise<unknown>
            act(() => {
                read = result.current.detail.refetch()
            })
            mockSource.shipVariant.mockResolvedValue({ status: 'shipped', experiment: FINISHED })
            mockSource.endExperiment.mockResolvedValue(FINISHED)
            const body = { conclusion: 'won' as const, open_cleanup_pr: false }
            await act(() =>
                result.current.finish.run({
                    request:
                        kind === 'ship'
                            ? {
                                  kind,
                                  variant: 'test',
                                  body: { ...body, variant_key: 'test', release_to_everyone: false },
                              }
                            : { kind, body },
                    preset: kind,
                    onFinished: jest.fn(),
                    onNeedsApproval: jest.fn(),
                })
            )
            await act(async () => {
                completeRead(RUNNING)
                await read
            })
            expect(result.current.detail.data).toEqual(FINISHED)
            expect(client.getQueryData(key)).toEqual(FINISHED)
            unmount()
            client.clear()
        }
    )

    it.each([
        ['launch', false],
        ['ship', false],
        ['approval', false],
        ['end', false],
        ['pause', false],
        ['resume', false],
        ['archive', false],
        ['conclusion', false],
        ['launch', true],
        ['ship', true],
        ['end', true],
        ['pause', true],
        ['resume', true],
        ['archive', true],
        ['conclusion', true],
    ] as const)('discards %s completion after the session changes (failed: %s)', async (action, failed) => {
        const { result, client, unmount } = setup()
        let finishRequest: (value: unknown) => void = () => undefined
        let failRequest: (reason: Error) => void = () => undefined
        const response = new Promise((resolve, reject) => {
            finishRequest = resolve
            failRequest = reject
        })
        const method =
            action === 'approval' || action === 'ship'
                ? 'shipVariant'
                : action === 'end'
                  ? 'endExperiment'
                  : action === 'pause'
                    ? 'pauseExperiment'
                    : action === 'resume'
                      ? 'resumeExperiment'
                      : action === 'archive'
                        ? 'archiveExperiment'
                        : action === 'conclusion'
                          ? 'updateExperiment'
                          : 'launchExperiment'
        mockSource[method].mockReturnValue(response)
        const onDone = jest.fn()
        const onNeedsApproval = jest.fn()
        let pending: Promise<void> = Promise.resolve()
        act(() => {
            if (action === 'launch') pending = result.current.launch.run(onDone)
            else if (action === 'archive') pending = result.current.archive.run(onDone)
            else if (action === 'conclusion')
                pending = result.current.conclusion.run({ conclusion: 'won', comment: '' }, onDone)
            else if (action === 'pause' || action === 'resume') pending = result.current.pause.run(action, onDone)
            else
                pending = result.current.finish.run({
                    request:
                        action === 'end'
                            ? { kind: 'end', body: { conclusion: 'won' } }
                            : { kind: 'ship', variant: 'test', body: { variant_key: 'test', conclusion: 'won' } },
                    preset: 'ship',
                    onFinished: onDone,
                    onNeedsApproval,
                })
        })
        await waitFor(() => expect(mockSource[method]).toHaveBeenCalled())
        unmount()
        setSessionTokens(null)
        client.clear()
        if (failed) failRequest(new Error('Response lost'))
        else
            finishRequest(
                action === 'approval'
                    ? { status: 'needs_approval', changeRequestId: 'request-old' }
                    : action === 'ship'
                      ? { status: 'shipped', experiment: FINISHED }
                      : FINISHED
            )
        await pending
        expect(client.getQueryData(key)).toBeUndefined()
        expect(onDone).not.toHaveBeenCalled()
        expect(onNeedsApproval).not.toHaveBeenCalled()
    })

    it('rereads the server after a pause response is lost', async () => {
        const { result, client, unmount } = setup()
        const paused = { ...RUNNING, status: 'paused', feature_flag: { ...RUNNING.feature_flag, active: false } }
        mockSource.pauseExperiment.mockImplementation(async () => {
            mockSource.fetchExperiment.mockResolvedValue(paused)
            throw new Error('Response lost')
        })
        await act(async () => {
            await expect(result.current.pause.run('pause', jest.fn())).rejects.toThrow('Response lost')
        })
        await waitFor(() => expect(result.current.detail.data).toEqual(paused))
        unmount()
        client.clear()
    })

    it('retains the complete shipping request for a retry after approval', async () => {
        const { result, client, unmount } = setup()
        mockSource.shipVariant.mockResolvedValue({ status: 'needs_approval', changeRequestId: 'request-1' })
        const request = {
            kind: 'ship' as const,
            variant: 'test',
            body: {
                variant_key: 'test',
                release_to_everyone: true,
                conclusion: 'won' as const,
                conclusion_comment: 'Keep this choice',
                open_cleanup_pr: true,
                repository: 'example-org/web',
            },
        }
        const onNeedsApproval = jest.fn()
        await act(() => result.current.finish.run({ request, preset: 'end', onFinished: jest.fn(), onNeedsApproval }))
        expect(onNeedsApproval).toHaveBeenCalledWith(expect.objectContaining({ request, preset: 'end' }))
        mockSource.shipVariant.mockResolvedValue({ status: 'shipped', experiment: FINISHED })
        await act(() =>
            result.current.finish.run({
                request: onNeedsApproval.mock.calls[0][0].request,
                preset: 'end',
                onFinished: jest.fn(),
                onNeedsApproval,
            })
        )
        expect(result.current.detail.data).toEqual(FINISHED)
        unmount()
        client.clear()
    })
})
