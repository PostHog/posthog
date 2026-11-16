import { act, fireEvent, render, screen } from '@testing-library/react-native'

import { ApiError } from '@/api/client'
import { RESOLVE_REASON_OPTIONS } from '@/model/verdictReasons'
import { OverlayHost } from '@/ui/OverlayPortal'
import { VerdictSheet } from './VerdictSheet'
import { resolveCopy } from './verdictCopy'

jest.mock('react-native-worklets', () => jest.requireActual('react-native-worklets/src/mock'))
jest.mock('react-native-reanimated', () => ({
    ...jest.requireActual('react-native-reanimated/mock'),
    useReducedMotion: () => true,
}))
jest.mock(
    'react-native-safe-area-context',
    () => jest.requireActual('react-native-safe-area-context/jest/mock').default
)
jest.mock('react-native-keyboard-controller', () => jest.requireActual('react-native-keyboard-controller/jest'))

test('confirms only with a reason, and keeps a refused transition open with the server message', async () => {
    const onConfirm = jest.fn(async () => {
        throw new ApiError(409, { error: 'This report is already resolved.' })
    })
    render(
        <VerdictSheet
            visible
            copy={resolveCopy('Checkout errors', false)}
            options={RESOLVE_REASON_OPTIONS}
            onClose={jest.fn()}
            onConfirm={onConfirm}
            pending={false}
            testID="resolve-sheet"
        />,
        { wrapper: OverlayHost }
    )

    expect(screen.getByTestId('resolve-sheet-confirm')).toBeDisabled()
    fireEvent.press(screen.getByTestId('resolve-sheet-confirm'))
    expect(onConfirm).not.toHaveBeenCalled()

    fireEvent.press(screen.getByTestId('resolve-sheet-reason-other'))
    fireEvent.changeText(screen.getByTestId('resolve-sheet-note'), 'Fixed by the vendor')
    expect(screen.getByTestId('resolve-sheet-confirm')).toBeEnabled()
    await act(async () => {
        fireEvent.press(screen.getByTestId('resolve-sheet-confirm'))
    })

    expect(onConfirm).toHaveBeenCalledWith('other', 'Fixed by the vendor')
    expect(screen.getByTestId('resolve-sheet-error')).toHaveTextContent('This report is already resolved.')
})
