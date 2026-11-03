import { memo, type ReactElement } from 'react'
import { Text, View } from 'react-native'

import { Dot } from '@/ui/Dot'
import { createStyles, type ThemeColors, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import { progressHeadline } from './sessionDisplay'
import type { SessionProgressItem, SessionProgressStep } from './types'

interface ProgressRowProps {
    item: SessionProgressItem
}

const STEP_COLORS: Record<SessionProgressStep['status'], keyof ThemeColors> = {
    pending: 'border',
    in_progress: 'blue',
    completed: 'tertiary',
    failed: 'orange',
}

export const ProgressRow = memo(function ProgressRow({ item }: ProgressRowProps): ReactElement | null {
    const colors = useColors()
    const styles = useStyles()
    const headline = progressHeadline(item.steps)
    if (headline === undefined) {
        return null
    }
    return (
        <View style={styles.card} testID={`session-progress-${item.id}`}>
            <Text style={styles.headline} numberOfLines={2}>
                {headline}
            </Text>
            <View style={styles.steps}>
                {item.steps.map((step) => (
                    <View key={step.key} style={styles.step}>
                        <View style={styles.dot}>
                            <Dot color={colors[STEP_COLORS[step.status]]} size={6} />
                        </View>
                        <View style={styles.stepBody}>
                            <Text
                                style={[styles.label, step.status === 'pending' && styles.labelPending]}
                                numberOfLines={2}
                            >
                                {step.label}
                            </Text>
                            {step.detail ? (
                                <Text style={styles.detail} numberOfLines={2}>
                                    {step.detail}
                                </Text>
                            ) : null}
                        </View>
                    </View>
                ))}
            </View>
        </View>
    )
})

const useStyles = createStyles(({ colors }) => ({
    card: {
        borderWidth: 1,
        borderColor: colors.hairline,
        borderRadius: radii.menuRow,
        paddingVertical: 12,
        paddingHorizontal: 14,
        gap: 10,
    },
    headline: {
        ...type.bodySmallStrong,
        color: colors.ink,
    },
    steps: {
        gap: 8,
    },
    step: {
        flexDirection: 'row',
        alignItems: 'flex-start',
        gap: 10,
    },
    dot: {
        height: 21,
        justifyContent: 'center',
    },
    stepBody: {
        flex: 1,
        minWidth: 0,
    },
    label: {
        ...type.bodySmall,
        color: colors.ink,
    },
    labelPending: {
        color: colors.tertiary,
    },
    detail: {
        ...type.meta,
        color: colors.muted,
        marginTop: 2,
    },
}))
