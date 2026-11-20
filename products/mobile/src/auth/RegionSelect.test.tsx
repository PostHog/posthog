import { act, fireEvent, render, screen } from '@testing-library/react-native'
import { BackHandler, View, type ViewInstance } from 'react-native'

import { OverlayHost } from '@/ui/OverlayPortal'

import { RegionSelect } from './RegionSelect'

jest.mock('react-native-worklets', () => jest.requireActual('react-native-worklets/src/mock'))
jest.mock('react-native-reanimated', () => ({
    ...jest.requireActual('react-native-reanimated/mock'),
    useReducedMotion: () => true,
}))
jest.mock(
    'react-native-safe-area-context',
    () => jest.requireActual('react-native-safe-area-context/jest/mock').default
)

describe('sign-in region menu', () => {
    beforeEach(() => {
        jest.spyOn(View.prototype as ViewInstance, 'measureInWindow').mockImplementation((callback) =>
            callback(24, 320, 300, 48)
        )
    })
    afterEach(() => jest.restoreAllMocks())

    test('selects EU, closes, and can reopen to switch back to US', () => {
        const onChange = jest.fn()
        const view = render(<RegionSelect value="us" onChange={onChange} disabled={false} />, {
            wrapper: OverlayHost,
        })

        fireEvent.press(screen.getByTestId('sign-in-region'))
        expect(screen.getByTestId('region-us')).toBeChecked()
        fireEvent.press(screen.getByTestId('region-eu'))
        expect(onChange).toHaveBeenLastCalledWith('eu')
        expect(screen.queryByTestId('sign-in-region-menu')).toBeNull()

        view.rerender(<RegionSelect value="eu" onChange={onChange} disabled={false} />)
        expect(screen.getByTestId('sign-in-region')).toHaveAccessibilityValue({ text: 'European Union' })
        fireEvent.press(screen.getByTestId('sign-in-region'))
        expect(screen.getByTestId('region-eu')).toBeChecked()
        fireEvent.press(screen.getByTestId('region-us'))
        expect(onChange).toHaveBeenLastCalledWith('us')
        expect(screen.getByTestId('sign-in-region')).toHaveProp('accessibilityState', {
            expanded: false,
            disabled: false,
        })
        expect(screen.queryByTestId('sign-in-region-menu')).toBeNull()
    })

    test.each(['outside', 'back'] as const)('dismisses with %s without changing region and can reopen', (method) => {
        const remove = jest.fn()
        const back = jest.spyOn(BackHandler, 'addEventListener').mockReturnValue({ remove })
        const onChange = jest.fn()
        render(<RegionSelect value="us" onChange={onChange} disabled={false} />, {
            wrapper: OverlayHost,
        })

        fireEvent.press(screen.getByTestId('sign-in-region'))
        if (method === 'outside') {
            fireEvent.press(screen.getByLabelText('Close', { includeHiddenElements: true }))
        } else {
            act(() => expect(back.mock.calls.at(-1)?.[1]({ type: 'hardwareBackPress', timeStamp: 0 })).toBe(true))
        }
        expect(onChange).not.toHaveBeenCalled()
        expect(screen.queryByTestId('sign-in-region-menu')).toBeNull()
        expect(remove).toHaveBeenCalled()
        fireEvent.press(screen.getByTestId('sign-in-region'))
        expect(screen.getByTestId('region-eu')).toBeTruthy()
    })
})
