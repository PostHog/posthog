import type { ReactElement } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { avatarPalette, colors } from './tokens'

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

export function paletteColorFor(seed: string): string {
    let hash = 0
    for (const char of seed) {
        hash = (hash * 31 + (char.codePointAt(0) ?? 0)) >>> 0
    }
    return avatarPalette[hash % avatarPalette.length] ?? colors.ink
}

export function Avatar({ name, color, seed, size = 32, fontSize = 12 }: AvatarProps): ReactElement {
    return (
        <View
            accessibilityLabel={name}
            accessibilityRole="image"
            style={[
                styles.circle,
                { width: size, height: size, borderRadius: size / 2 },
                { backgroundColor: color ?? paletteColorFor(seed ?? name) },
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
        color: colors.white,
        fontWeight: '600',
    },
})
