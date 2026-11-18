import { act, renderHook } from '@testing-library/react-native'
import { createElement, type ReactNode } from 'react'
import { useColorScheme } from 'react-native'

import { useAppearanceStore } from '@/ui/appearanceStore'

import {
    createStyles,
    darkColors,
    GlassSurfaceContext,
    glassThemes,
    lightColors,
    useColorSchemeName,
    useColors,
} from './theme'

const COLOR = /^(#[0-9A-F]{6}|rgba\(\d{1,3},\d{1,3},\d{1,3},(0|1|0?\.\d+)\))$/

describe('theme', () => {
    afterEach(() => {
        jest.mocked(useColorScheme).mockReturnValue('light')
        act(() => useAppearanceStore.setState({ appearance: 'system' }))
    })

    test('both palettes define every token as a hex or rgba color', () => {
        expect(Object.keys(darkColors).sort()).toEqual(Object.keys(lightColors).sort())
        const glassColors = [...Object.values(glassThemes.light.colors), ...Object.values(glassThemes.dark.colors)]
        for (const value of [...Object.values(lightColors), ...Object.values(darkColors), ...glassColors]) {
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

    test('content on a glass card gets translucent fills, and the card owner can ask for them outside it', () => {
        const useStyles = createStyles(({ colors }) => ({ pill: { backgroundColor: colors.sunken } }))
        const onCard = ({ children }: { children: ReactNode }) =>
            createElement(GlassSurfaceContext.Provider, { value: true }, children)

        expect(renderHook(() => useStyles()).result.current.pill.backgroundColor).toBe(lightColors.sunken)
        const nested = renderHook(() => useStyles(), { wrapper: onCard }).result.current
        expect(nested.pill.backgroundColor).toBe(glassThemes.light.colors.sunken)
        expect(renderHook(() => useStyles(true)).result.current).toBe(nested)
        expect(renderHook(() => useColors(), { wrapper: onCard }).result.current.ink).toBe(lightColors.ink)
    })

    test('an Appearance override wins over the device scheme', () => {
        const { result } = renderHook(() => useColorSchemeName())
        expect(result.current).toBe('light')

        act(() => useAppearanceStore.setState({ appearance: 'dark' }))
        expect(result.current).toBe('dark')
    })
})
