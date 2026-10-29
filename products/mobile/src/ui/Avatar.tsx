import type { ReactElement } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { useTheme } from './theme'

interface AvatarProps {
    name: string
    color?: string
    seed?: string
    size?: number
    fontSize?: number
}

export function initialsFor(name: string): string {
    const words = name.trim().split(/\s+/).filter(Boolean)
    const letters = words.length > 1 ? [words[0], words[words.length - 1]] : words
    return letters
        .map((word) => word?.[0] ?? '')
        .join('')
        .toUpperCase()
}

export function paletteColorFor(seed: string, palette: readonly string[]): string {
    let hash = 0
    for (const char of seed) {
        hash = (hash * 31 + (char.codePointAt(0) ?? 0)) >>> 0
    }
    return palette[hash % palette.length] ?? 'gray'
}

export function Avatar({ name, color, seed, size = 32, fontSize = 12 }: AvatarProps): ReactElement {
    const { avatarPalette } = useTheme()
    return (
        <View
            accessibilityLabel={name}
            accessibilityRole="image"
            style={[
                styles.circle,
                { width: size, height: size, borderRadius: size / 2 },
                { backgroundColor: color ?? paletteColorFor(seed ?? name, avatarPalette) },
            ]}
        >
            <Text style={[styles.initials, { fontSize, lineHeight: Math.round(fontSize * 1.2) }]}>
                {initialsFor(name)}
            </Text>
        </View>
    )
}

const styles = StyleSheet.create({
    circle: {
        alignItems: 'center',
        justifyContent: 'center',
    },
    initials: {
        // Literal white: it reads on every avatar palette color in both schemes.
        color: 'white',
        fontWeight: '600',
    },
})
