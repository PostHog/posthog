import { Fragment, type ReactElement, useEffect, useRef, useState } from 'react'
import { ActivityIndicator, Text, View } from 'react-native'
import { useReducedMotion } from 'react-native-reanimated'

import { groupThousands } from '@/model/adapters/text'
import { InfoIcon } from '@/ui/icons/InfoIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

const TWEEN_MS = 300
const FLASH_MS = 600

interface Stat {
    key: string
    label: string
    about: string
    value: number | null
    loading?: boolean
}

interface LiveStatsProps {
    usersOnline: number | null
    uniqueVisitors: number | null
    pageviews: number | null
    onAbout: (text: string) => void
    audience?: 'web' | 'mobile' | 'mixed'
    metrics?: Stat[]
    compact?: boolean
}

export function LiveStats({
    usersOnline,
    uniqueVisitors,
    pageviews,
    onAbout,
    audience = 'web',
    metrics,
    compact = false,
}: LiveStatsProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const stats: Stat[] = metrics ?? [
        {
            key: 'users-online',
            label: 'Users online',
            about: 'Users active right now.',
            value: usersOnline,
        },
        {
            key: 'unique-visitors',
            label: audience === 'web' ? 'Unique visitors' : 'Active users',
            about:
                audience === 'web' ? 'Unique visitors in the last 30 minutes.' : 'Unique users in the last 30 minutes.',
            value: uniqueVisitors,
        },
        { key: 'pageviews', label: 'Pageviews', about: 'Pages viewed in the last 30 minutes.', value: pageviews },
    ]
    return (
        <View style={styles.card} testID="live-stats">
            {stats.map((stat, index) => (
                <Fragment key={stat.key}>
                    {index > 0 ? <View style={styles.divider} /> : null}
                    <Pressable44
                        style={styles.stat}
                        onPress={() => onAbout(stat.about)}
                        accessibilityLabel={`${stat.label}: ${stat.value === null ? (stat.loading !== false ? 'Loading' : 'unavailable') : groupThousands(stat.value)}. ${stat.about}`}
                        pressedBackground={colors.pressed}
                        testID={`live-stat-${stat.key}-label`}
                    >
                        <View style={[styles.labelButton, compact && styles.compactLabel]}>
                            <Text style={styles.label} numberOfLines={2}>
                                {stat.label}
                            </Text>
                            <InfoIcon size={12} color={colors.tertiary} />
                        </View>
                        {stat.value === null && stat.loading !== false ? (
                            <View style={styles.loading}>
                                <ActivityIndicator
                                    color={colors.tertiary}
                                    accessibilityLabel={`Loading ${stat.label}`}
                                    testID={`live-stat-${stat.key}-loading`}
                                />
                            </View>
                        ) : (
                            <AnimatedCount value={stat.value} label={stat.label} testID={`live-stat-${stat.key}`} />
                        )}
                    </Pressable44>
                </Fragment>
            ))}
        </View>
    )
}

function AnimatedCount({
    value,
    label,
    testID,
}: {
    value: number | null
    label: string
    testID: string
}): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const reduced = useReducedMotion()
    const [shown, setShown] = useState(value)
    const [changing, setChanging] = useState(false)
    const shownRef = useRef(value)
    useEffect(() => {
        const from = shownRef.current
        if (value === null || from === null || value === from) {
            shownRef.current = value
            setShown(value)
            return undefined
        }
        setChanging(true)
        const flash = setTimeout(() => setChanging(false), FLASH_MS)
        if (reduced) {
            shownRef.current = value
            setShown(value)
            return () => clearTimeout(flash)
        }
        const start = Date.now()
        let frame = 0
        const step = (): void => {
            const progress = Math.min(1, (Date.now() - start) / TWEEN_MS)
            const eased = 1 - (1 - progress) * (1 - progress)
            shownRef.current = Math.round(from + (value - from) * eased)
            setShown(shownRef.current)
            if (progress < 1) {
                frame = requestAnimationFrame(step)
            }
        }
        frame = requestAnimationFrame(step)
        return () => {
            cancelAnimationFrame(frame)
            clearTimeout(flash)
        }
    }, [value, reduced])
    return (
        <Text
            style={[styles.value, changing && { color: colors.blue }]}
            numberOfLines={1}
            adjustsFontSizeToFit
            accessibilityLabel={`${label}: ${value === null ? 'not loaded' : groupThousands(value)}`}
            accessibilityLiveRegion="polite"
            testID={testID}
        >
            {shown === null ? '–' : groupThousands(shown)}
        </Text>
    )
}

const useStyles = createStyles(({ colors }) => ({
    loading: { height: 38, alignItems: 'flex-start', justifyContent: 'center' },
    card: {
        flexDirection: 'row',
        paddingVertical: 12,
        paddingHorizontal: 4,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
    },
    stat: {
        flex: 1,
        minWidth: 0,
        gap: 4,
        paddingHorizontal: 10,
    },
    divider: {
        width: 1,
        marginVertical: 4,
        backgroundColor: colors.hairline,
    },
    labelButton: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 4,
        minHeight: 32,
        borderRadius: 6,
    },
    label: {
        ...type.eyebrow,
        textTransform: 'uppercase',
        color: colors.tertiary,
        flexShrink: 1,
    },
    compactLabel: {
        minHeight: 20,
    },
    value: {
        ...type.screenTitle,
        color: colors.ink,
        fontVariant: ['tabular-nums'],
    },
}))
