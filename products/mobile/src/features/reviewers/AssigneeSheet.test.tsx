import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'

import { useDemoMode } from '@/demo/demoMode'
import { DEMO_PEOPLE } from '@/demo/fixtures'
import type { Reviewer } from '@/model/types'
import { OverlayHost } from '@/ui/OverlayPortal'

import { AssigneeSheet } from './AssigneeSheet'

jest.mock('react-native-worklets', () => jest.requireActual('react-native-worklets/src/mock'))
jest.mock('react-native-reanimated', () => ({
    ...jest.requireActual('react-native-reanimated/mock'),
    useReducedMotion: () => true,
}))
jest.mock(
    'react-native-safe-area-context',
    () => jest.requireActual('react-native-safe-area-context/jest/mock').default
)

const EXISTING = DEMO_PEOPLE[0] as Reviewer
const ADDED = DEMO_PEOPLE[1] as Reviewer

describe('AssigneeSheet', () => {
    test.each([
        ['an equivalent assignment', [{ ...EXISTING }]],
        ['a changed assignment', []],
    ] as const)('keeps unsaved edits through %s and starts fresh on reopening', async (_name, refreshed) => {
        useDemoMode.getState().setEnabled(true)
        const client = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } })
        const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
            <QueryClientProvider client={client}>
                <OverlayHost>{children}</OverlayHost>
            </QueryClientProvider>
        )
        const onSave = jest.fn(async () => undefined)
        const props = { githubOnlyCount: 0, onClose: jest.fn(), onSave, pending: false }
        const view = render(<AssigneeSheet {...props} visible current={[EXISTING]} />, { wrapper })
        try {
            await waitFor(() => expect(screen.getByTestId(`assignee-${ADDED.uuid}`)).toBeTruthy())
            fireEvent.changeText(screen.getByTestId('assignee-search'), ADDED.name)
            fireEvent.press(screen.getByTestId(`assignee-${ADDED.uuid}`))
            view.rerender(<AssigneeSheet {...props} visible current={[...refreshed]} />)
            expect(screen.getByTestId('assignee-search').props.value).toBe(ADDED.name)
            expect(screen.getByTestId(`assignee-${ADDED.uuid}`).props.accessibilityState.checked).toBe(true)
            await act(async () => fireEvent.press(screen.getByTestId('assignee-done')))
            expect(onSave).toHaveBeenCalledWith([EXISTING.uuid, ADDED.uuid])
            view.rerender(<AssigneeSheet {...props} visible={false} current={[...refreshed]} />)
            view.rerender(<AssigneeSheet {...props} visible current={[...refreshed]} />)
            expect(screen.getByTestId('assignee-search').props.value).toBe('')
            expect(screen.getByTestId(`assignee-${ADDED.uuid}`).props.accessibilityState.checked).toBe(false)
            expect(screen.queryByTestId('assignee-done')).toBeNull()
        } finally {
            view.unmount()
            client.clear()
            useDemoMode.getState().setEnabled(false)
        }
    })
})
