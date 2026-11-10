import { render, screen } from '@testing-library/react-native'
import { Text } from 'react-native'
import { BottomSheet } from './BottomSheet'
import { DisplayRegionContext } from './displayRegionContext'
import { SceneDimensionsContext } from './sceneDimensions'
import { useSceneDimensions } from './useSceneDimensions'

jest.mock(
    'react-native-safe-area-context',
    () => jest.requireActual('react-native-safe-area-context/jest/mock').default
)

jest.mock('react-native-worklets', () => jest.requireActual('react-native-worklets/src/mock'))
jest.mock('react-native-reanimated', () => ({
    ...jest.requireActual('react-native-reanimated/mock'),
    useReducedMotion: () => true,
}))

function Contents(): React.JSX.Element {
    const { width, height } = useSceneDimensions()
    return (
        <Text testID="available-size">
            {width}x{height}
        </Text>
    )
}

describe('BottomSheet', () => {
    test('gives its contents the selected horizontal pane height instead of the full scene', () => {
        render(
            <SceneDimensionsContext.Provider value={{ width: 669, height: 951 }}>
                <DisplayRegionContext.Provider
                    value={[
                        { kind: 'division', occludesContent: false, frame: { x: 0, y: 440, width: 669, height: 20 } },
                    ]}
                >
                    <BottomSheet visible onClose={() => undefined}>
                        <Contents />
                    </BottomSheet>
                </DisplayRegionContext.Provider>
            </SceneDimensionsContext.Provider>
        )
        expect(screen.getByTestId('available-size')).toHaveTextContent('600x491')
    })
})
