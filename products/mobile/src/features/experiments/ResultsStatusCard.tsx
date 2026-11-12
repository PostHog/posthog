import type { ReactElement } from 'react'
import { ActivityIndicator, Text, View } from 'react-native'

import { Dot } from '@/ui/Dot'
import { createStyles, type ThemeColors, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import type { StatusCardModel, StatusTone } from './detailModel'

function toneColor(tone: StatusTone, colors: ThemeColors): string {
    switch (tone) {
        case 'fresh':
            return colors.diffGreen
        case 'aging':
            return colors.yellow
        case 'stale':
            return colors.diffRed
        case 'info':
            return colors.blue
        case 'final':
            return colors.purple
        default:
            return colors.tertiary
    }
}

/**
 * Which run the numbers come from and how old they are. No button: a pull refreshes, and while a recalculation runs
 * the card counts the metrics as they finish.
 */
export function ResultsStatusCard({ model }: { model: StatusCardModel }): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const label = [model.strong, model.text].filter(Boolean).join(' · ')
    return (
        <View
            style={styles.card}
            accessible
            accessibilityRole="text"
            accessibilityLabel={model.sub ? `${label}. ${model.sub}` : label}
            accessibilityLiveRegion="polite"
            testID="experiment-results-status"
        >
            <View style={styles.line}>
                {model.spinner ? (
                    <ActivityIndicator size="small" color={colors.secondary} style={styles.spinner} />
                ) : (
                    <Dot color={toneColor(model.tone, colors)} size={8} />
                )}
                <Text style={styles.text}>
                    {model.strong ? <Text style={styles.strong}>{model.strong}</Text> : null}
                    {model.strong && model.text ? ' · ' : ''}
                    {model.text}
                </Text>
            </View>
            {model.sub ? <Text style={styles.sub}>{model.sub}</Text> : null}
            {model.progress !== null ? (
                <View style={styles.track}>
                    <View style={[styles.fill, { width: `${Math.round(model.progress * 100)}%` }]} />
                </View>
            ) : null}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    card: {
        marginTop: 12,
        paddingHorizontal: 14,
        paddingVertical: 12,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
        gap: 8,
    },
    line: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
    },
    spinner: {
        width: 16,
        height: 16,
        transform: [{ scale: 0.8 }],
    },
    text: {
        ...type.metaSmall,
        color: colors.secondary,
        flex: 1,
    },
    strong: {
        fontWeight: '600',
        color: colors.ink,
    },
    sub: {
        ...type.meta,
        color: colors.tertiary,
        paddingLeft: 16,
    },
    track: {
        height: 4,
        borderRadius: 2,
        backgroundColor: colors.sunken,
        overflow: 'hidden',
    },
    fill: {
        height: 4,
        borderRadius: 2,
        backgroundColor: colors.blue,
    },
}))
