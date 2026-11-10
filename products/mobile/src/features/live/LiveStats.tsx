import { Fragment, type ReactElement, useEffect, useRef, useState } from 'react'
import { Text, View } from 'react-native'
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
}

interface LiveStatsProps {
    usersOnline: number | null
    uniqueVisitors: number | null
    pageviews: number | null
    onAbout: (text: string) => void
}

/** The web's three live numbers in columns with dividers. A changed number counts to its new value and flashes blue. */
export function LiveStats({ usersOnline, uniqueVisitors, pageviews, onAbout }: LiveStatsProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const stats: Stat[] = [
        {
            key: 'users-online',
            label: 'Users online',
            about: 'People active on your site right now.',
            value: usersOnline,
        },
        {
            key: 'unique-visitors',
            label: 'Unique visitors',
            about: 'Distinct visitors in the last 30 minutes.',
            value: uniqueVisitors,
        },
        { key: 'pageviews', label: 'Pageviews', about: 'Total pages viewed in the last 30 minutes.', value: pageviews },
    ]
    return (
        <View style={styles.card} testID="live-stats">
            {stats.map((stat, index) => (
                <Fragment key={stat.key}>
                    {index > 0 ? <View style={styles.divider} /> : null}
                    <View style={styles.stat}>
                        <Pressable44
                            onPress={() => onAbout(stat.about)}
                            accessibilityLabel={`${stat.label}. ${stat.about}`}
                            pressedBackground={colors.pressed}
                            style={styles.labelButton}
                            testID={`live-stat-${stat.key}-label`}
                        >
                            <Text style={styles.label} numberOfLines={2}>
                                {stat.label}
                            </Text>
                            <InfoIcon size={12} color={colors.tertiary} />
                        </Pressable44>
                        <AnimatedCount value={stat.value} label={stat.label} testID={`live-stat-${stat.key}`} />
                    </View>
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
    value: {
        fontSize: 28,
        lineHeight: 34,
        fontWeight: '700',
        letterSpacing: -0.4,
        color: colors.ink,
        fontVariant: ['tabular-nums'],
    },
}))
