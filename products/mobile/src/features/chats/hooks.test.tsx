import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'

import { useAuthStore } from '@/auth/authStore'

import { useChatList } from './hooks'

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
        // Otherwise the unmount at cleanup starts a five-minute garbage-collection timer that holds jest open.
        const queryClient = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } })
        const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
            <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
        )
        const { result } = renderHook(() => useChatList(), { wrapper })

        await waitFor(() => expect(result.current.isLoading).toBe(false))
        expect(reloadAccount).toHaveBeenCalledTimes(1)
        expect(result.current.isError).toBe(isError)
        expect(result.current.data).toEqual(isError ? undefined : [])
    })
})
