import { renderHook } from '@testing-library/react-native'
import { useColorScheme } from 'react-native'

import { createStyles, darkColors, lightColors } from './theme'

const COLOR = /^(#[0-9A-F]{6}|rgba\(\d{1,3},\d{1,3},\d{1,3},(0|1|0?\.\d+)\))$/

describe('theme', () => {
    afterEach(() => {
        jest.mocked(useColorScheme).mockReturnValue('light')
    })

    test('both palettes define every token as a hex or rgba color', () => {
        expect(Object.keys(darkColors).sort()).toEqual(Object.keys(lightColors).sort())
        for (const value of [...Object.values(lightColors), ...Object.values(darkColors)]) {
            expect(value).toMatch(COLOR)
        }
    })

    test('createStyles builds one sheet per scheme and reuses it', () => {
        const useStyles = createStyles(({ colors }) => ({ card: { backgroundColor: colors.surface } }))
        const { result, rerender } = renderHook(() => useStyles())
        const light = result.current
        rerender({})
        expect(result.current).toBe(light)

        jest.mocked(useColorScheme).mockReturnValue('dark')
        rerender({})
        const dark = result.current
        expect(dark.card.backgroundColor).toBe(darkColors.surface)
        expect(light.card.backgroundColor).toBe(lightColors.surface)
        rerender({})
        expect(result.current).toBe(dark)
    })
})
