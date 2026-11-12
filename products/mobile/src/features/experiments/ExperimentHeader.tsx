import type { ReactElement } from 'react'
import { type LayoutChangeEvent, Text, View } from 'react-native'

import { Dot } from '@/ui/Dot'
import { Eyebrow } from '@/ui/Eyebrow'
import { ClockIcon } from '@/ui/icons/ClockIcon'
import { FlagIcon } from '@/ui/icons/FlagIcon'
import { createStyles, type ThemeColors, useColors } from '@/ui/theme'
import { fonts, iconSizes, radii, type } from '@/ui/tokens'

import type { Byline } from './detailModel'
import type { ExperimentStatus } from './experimentModel'

const STATUS_LABEL: Record<ExperimentStatus, string> = {
    draft: 'Draft',
    running: 'Running',
    paused: 'Paused',
    frozen: 'Exposure frozen',
    complete: 'Complete',
}

function statusColor(status: ExperimentStatus, colors: ThemeColors): string {
    switch (status) {
        case 'running':
            return colors.diffGreen
        case 'paused':
            return colors.orange
        case 'frozen':
            return colors.blue
        case 'complete':
            return colors.purple
        default:
            return colors.tertiary
    }
}

export function ExperimentStatusChip({ status }: { status: ExperimentStatus }): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <View style={styles.chip} testID="experiment-status-chip">
            <Dot color={statusColor(status, colors)} size={7} />
            <Text style={styles.chipText}>{STATUS_LABEL[status]}</Text>
        </View>
    )
}

interface ExperimentHeaderProps {
    onTitleLayout?: (event: LayoutChangeEvent) => void
    eyebrow: string
    status: ExperimentStatus
    name: string
    byline: Byline
}

/** Status, name, how long it ran, the flag and the stats method. Nothing here is tappable. */
export function ExperimentHeader({
    onTitleLayout,
    eyebrow,
    status,
    name,
    byline,
}: ExperimentHeaderProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const [flagKey, ...rest] = byline.flag.split(' · ')
    return (
        <View>
            <View onLayout={onTitleLayout}>
                <View style={styles.eyebrowRow}>
                    <Eyebrow>{eyebrow}</Eyebrow>
                    <ExperimentStatusChip status={status} />
                </View>
                <Text style={styles.headline} accessibilityRole="header" numberOfLines={4} testID="experiment-title">
                    {name}
                </Text>
            </View>
            <View style={styles.byline}>
                <View style={styles.bylineRow}>
                    <ClockIcon size={iconSizes.inline} color={colors.tertiary} />
                    <Text style={styles.bylineText} numberOfLines={1} testID="experiment-byline-timing">
                        {byline.timing}
                    </Text>
                </View>
                <View style={styles.bylineRow}>
                    <FlagIcon size={iconSizes.inline} color={colors.tertiary} />
                    <Text style={styles.bylineText} numberOfLines={2} testID="experiment-byline-flag">
                        Flag <Text style={styles.mono}>{flagKey}</Text>
                        {rest.length ? ` · ${rest.join(' · ')}` : ''}
                    </Text>
                </View>
            </View>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    eyebrowRow: {
        flexDirection: 'row',
        flexWrap: 'wrap',
        alignItems: 'center',
        gap: 8,
    },
    chip: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
        height: 26,
        paddingHorizontal: 10,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
    },
    chipText: {
        fontSize: 13,
        fontWeight: '500',
        color: colors.ink,
    },
    headline: {
        ...type.headline,
        color: colors.ink,
        marginTop: 10,
    },
    byline: {
        marginTop: 8,
        gap: 4,
    },
    bylineRow: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
    },
    bylineText: {
        ...type.metaSmall,
        color: colors.secondary,
        flexShrink: 1,
    },
    mono: {
        fontFamily: fonts.mono,
        fontSize: 13,
        color: colors.secondary,
    },
}))
