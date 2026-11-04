import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, type RenderHookResult, renderHook, waitFor } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'

import type { TaskSummaryApi } from '@/api/tasks'
import { useAuthStore } from '@/auth/authStore'

import { useArchiveChat, useChatList } from './hooks'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
jest.mock('expo-notifications', () => ({}))
jest.mock('@/auth/useProjectScope', () => {
    const scope = { host: 'https://app.example.com', projectId: 2 }
    return { useProjectScope: () => scope }
})
jest.mock('@/demo/demoMode', () => ({
    ...jest.requireActual('@/demo/demoMode'),
    useDataMode: () => 'live',
}))
jest.mock('@/api/tasks', () => ({ listMySessions: jest.fn(), setTaskArchived: jest.fn() }))

const mocked = jest.requireMock('@/api/tasks') as {
    listMySessions: jest.Mock
    setTaskArchived: jest.Mock
}

function session(id: string, lastActivityAt: string): TaskSummaryApi {
    return {
        id,
        title: `Chat ${id}`,
        origin_product: 'posthog_ai',
        archived: false,
        latest_run: null,
        created_at: lastActivityAt,
        updated_at: lastActivityAt,
        last_activity_at: lastActivityAt,
    }
}

interface ChatsHooks {
    list: ReturnType<typeof useChatList>
    archive: ReturnType<typeof useArchiveChat>
}

function renderChats(): RenderHookResult<ChatsHooks, unknown> {
    // Otherwise the unmount at cleanup starts a five-minute garbage-collection timer that holds jest open.
    const queryClient = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity, retry: false } } })
    const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )
    return renderHook(() => ({ list: useChatList(), archive: useArchiveChat() }), { wrapper })
}

describe('chats hooks', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    describe('useChatList', () => {
        test.each<[string, string | null, boolean]>([
            ['shows the account error when the reload fails', 'Your account did not load.', true],
            ['shows an empty list when the reload brings no id', null, false],
        ])('without a numeric user id, %s', async (_, accountError, isError) => {
            const reloadAccount = jest.fn(async (): Promise<void> => {
                useAuthStore.setState({ accountLoading: false, accountError })
            })
            useAuthStore.setState({
                user: { uuid: 'u1', distinctId: 'd1', email: 'a@example.com', name: 'A' },
                accountLoading: false,
                accountError: null,
                reloadAccount,
            })
            const { result } = renderChats()

            await waitFor(() => expect(result.current.list.isLoading).toBe(false))
            expect(reloadAccount).toHaveBeenCalledTimes(1)
            expect(result.current.list.isError).toBe(isError)
            expect(result.current.list.data).toEqual(isError ? undefined : [])
        })
    })

    describe('useArchiveChat', () => {
        beforeEach(() => {
            useAuthStore.setState({
                user: { id: 7, uuid: 'u1', distinctId: 'd1', email: 'a@example.com', name: 'A' },
                accountLoading: false,
                accountError: null,
            })
            mocked.listMySessions.mockResolvedValue([
                session('task-1', '2026-10-15T10:00:00Z'),
                session('task-2', '2026-10-14T10:00:00Z'),
            ])
        })

        test.each([
            ['stays hidden after the request succeeds', true],
            ['comes back when the request fails', false],
        ])('an archived row leaves the list at once and %s', async (_, succeeds) => {
            let settle: (() => void) | undefined
            mocked.setTaskArchived.mockImplementation(
                () =>
                    new Promise<void>((resolve, reject) => {
                        settle = () => (succeeds ? resolve() : reject(new Error('offline')))
                    })
            )
            const { result } = renderChats()
            await waitFor(() => expect(result.current.list.data).toHaveLength(2))
            const [first] = result.current.list.data ?? []
            if (!first) {
                throw new Error('Missing chat row')
            }

            let outcome: Promise<void> | undefined
            act(() => {
                outcome = result.current.archive.archive(first)
                void result.current.archive.archive(first).catch(() => undefined)
            })
            await waitFor(() => expect(result.current.list.data?.map((item) => item.sourceId)).toEqual(['task-2']))
            expect(mocked.setTaskArchived).toHaveBeenCalledWith('task-1', true)
            expect(mocked.setTaskArchived).toHaveBeenCalledTimes(1)

            await act(async () => {
                settle?.()
                await outcome?.catch(() => undefined)
            })
            const expected = succeeds ? ['task-2'] : ['task-1', 'task-2']
            await waitFor(() => expect(result.current.list.data?.map((item) => item.sourceId)).toEqual(expected))
        })

        test.each([
            [false, true],
            [true, true],
            [true, false],
        ])(
            'Undo restores the row with archive pending %s and restore succeeds %s',
            async (archivePending, succeeds) => {
                let finishArchive: (() => void) | undefined
                let finishRestore: (() => void) | undefined
                mocked.setTaskArchived.mockImplementation((_taskId: string, archived: boolean): Promise<void> => {
                    if (archived && !archivePending) {
                        return Promise.resolve()
                    }
                    return new Promise<void>((resolve, reject) => {
                        if (archived) {
                            finishArchive = resolve
                        } else {
                            finishRestore = () => (succeeds ? resolve() : reject(new Error('offline')))
                        }
                    })
                })
                const { result } = renderChats()
                await waitFor(() => expect(result.current.list.data).toHaveLength(2))
                const [first] = result.current.list.data ?? []
                if (!first) {
                    throw new Error('Missing chat row')
                }

                let archiveOutcome: Promise<void> | undefined
                act(() => {
                    archiveOutcome = result.current.archive.archive(first)
                })
                await waitFor(() => expect(result.current.list.data?.map((item) => item.sourceId)).toEqual(['task-2']))

                let restoreOutcome: Promise<void> | undefined
                act(() => {
                    restoreOutcome = result.current.archive.restore(first).catch(() => undefined)
                })
                await waitFor(() =>
                    expect(result.current.list.data?.map((item) => item.sourceId)).toEqual(['task-1', 'task-2'])
                )
                if (archivePending) {
                    expect(mocked.setTaskArchived).toHaveBeenCalledTimes(1)
                }
                await act(async () => {
                    finishArchive?.()
                    await archiveOutcome
                })
                await waitFor(() => expect(mocked.setTaskArchived).toHaveBeenLastCalledWith('task-1', false))
                await act(async () => {
                    finishRestore?.()
                    await restoreOutcome
                })
                const expected = succeeds ? ['task-1', 'task-2'] : ['task-2']
                await waitFor(() => expect(result.current.list.data?.map((item) => item.sourceId)).toEqual(expected))
            }
        )

        test('archives a directly opened task that is not in the cached list', async () => {
            mocked.setTaskArchived.mockResolvedValue(undefined)
            const { result } = renderChats()
            await waitFor(() => expect(result.current.list.data).toHaveLength(2))
            await act(async () => result.current.archive.archive({ sourceId: 'direct-task' }))
            expect(mocked.setTaskArchived).toHaveBeenCalledWith('direct-task', true)
            expect(result.current.list.data?.map((item) => item.sourceId)).toEqual(['task-1', 'task-2'])
        })
    })
})
