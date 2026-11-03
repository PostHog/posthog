import { act, fireEvent, render, screen } from '@testing-library/react-native'

import { track } from '@/lib/analytics'
import { useAppearanceStore } from '@/ui/appearanceStore'
import { AppearanceGroup } from './AppearanceGroup'

jest.mock('@/lib/analytics', () => ({ track: jest.fn() }))

describe('AppearanceGroup', () => {
    afterEach(() => {
        act(() => useAppearanceStore.setState({ appearance: 'system' }))
    })

    test('choosing Dark saves the override and reports the change', () => {
        render(<AppearanceGroup />)
        expect(screen.getByTestId('appearance-system').props.accessibilityState).toMatchObject({ checked: true })

        fireEvent.press(screen.getByTestId('appearance-dark'))

        expect(useAppearanceStore.getState().appearance).toBe('dark')
        expect(screen.getByTestId('appearance-dark').props.accessibilityState).toMatchObject({ checked: true })
        expect(track).toHaveBeenCalledWith('mobile_appearance_changed', {
            appearance: 'dark',
            previous_appearance: 'system',
        })
    })
})
