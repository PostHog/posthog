import { fireEvent, render, screen } from '@testing-library/react-native'
import { type ReactElement, useState } from 'react'
import { Text, TextInput, View } from 'react-native'
import { useReservedRegions } from 'react-native-reserved-regions'

import { useDisplayRegions } from './displayRegionContext'
import { MobileScene } from './MobileScene'

let mockLeft = 0
jest.mock('react-native-safe-area-context', () => ({
    ...jest.requireActual('react-native-safe-area-context/jest/mock').default,
    useSafeAreaInsets: () => ({ left: mockLeft, right: 84 - mockLeft, top: 0, bottom: 0 }),
}))

function Draft(): ReactElement {
    const [note, setNote] = useState('')
    const regions = useDisplayRegions()
    return (
        <View>
            <Text testID="fold">{regions[0]?.frame.x}</Text>
            <TextInput testID="note" value={note} onChangeText={setNote} />
        </View>
    )
}

test('keeps a draft while translating a window fold to either safe edge', () => {
    jest.mocked(useReservedRegions).mockReturnValue([
        { kind: 'division', occludesContent: false, frame: { x: 455.5, y: 0, width: 40, height: 669 } },
    ])
    const view = render(
        <MobileScene>
            <Draft />
        </MobileScene>
    )
    const input = screen.getByTestId('note')
    fireEvent.changeText(input, 'Keep this note')
    expect(screen.getByTestId('fold').props.children).toBe(455.5)
    mockLeft = 84
    view.rerender(
        <MobileScene>
            <Draft />
        </MobileScene>
    )
    expect(screen.getByTestId('fold').props.children).toBe(371.5)
    expect(screen.getByTestId('note')).toBe(input)
    expect(input.props.value).toBe('Keep this note')
    view.unmount()
    mockLeft = 0
    jest.mocked(useReservedRegions).mockReturnValue([])
})
