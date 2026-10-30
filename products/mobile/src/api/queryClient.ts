import { focusManager, QueryClient } from '@tanstack/react-query'
import { AppState } from 'react-native'

// TanStack's default focus listener needs `window` visibility events, which React Native lacks, so the focus state never
// changed on iOS or Android. App state drives it instead.
focusManager.setEventListener((setFocused) => {
    const subscription = AppState.addEventListener('change', (state) => setFocused(state === 'active'))
    return () => subscription.remove()
})

export const queryClient = new QueryClient({
    defaultOptions: {
        queries: {
            staleTime: 30_000,
            retry: 1,
            // Focus refetch stays opt-in per query. With the 30 s stale time, a default of true would refetch the inbox
            // and chats on every return to the app.
            refetchOnWindowFocus: false,
        },
    },
})
