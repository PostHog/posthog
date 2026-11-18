import type { ReactElement } from 'react'
import { type StyleProp, StyleSheet, Text, View, type ViewStyle } from 'react-native'

import { appVariant, environmentBadge } from '@/lib/environment'

import { environmentRibbonColors, radii, type } from './tokens'

interface EnvironmentRibbonProps {
    /** The PostHog host the screen talks to, or null when there is none yet. */
    host: string | null
    style?: StyleProp<ViewStyle>
}

/** A band that tells a dev or preview build apart from the store app, which never shows one. */
export function EnvironmentRibbon({ host, style }: EnvironmentRibbonProps): ReactElement | null {
    const badge = environmentBadge(appVariant, host)
    if (!badge) {
        return null
    }
    const palette = environmentRibbonColors[badge.tone]
    return (
        <View style={[styles.ribbon, { backgroundColor: palette.background }, style]} testID="environment-ribbon">
            <Text style={[styles.label, { color: palette.text }]} numberOfLines={1}>
                {badge.label}
            </Text>
        </View>
    )
}

const styles = StyleSheet.create({
    ribbon: {
        minHeight: 28,
        borderRadius: radii.tile,
        paddingHorizontal: 12,
        paddingVertical: 4,
        alignItems: 'center',
        justifyContent: 'center',
    },
    label: {
        ...type.meta,
        fontWeight: '600',
    },
})
