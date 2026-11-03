import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import type { IssueStatusApi } from '@/api/errorTracking'
import { Dot } from '@/ui/Dot'
import { ArrowUpIcon } from '@/ui/icons/ArrowUpIcon'
import { createStyles, type ThemeColors, useColors } from '@/ui/theme'
import { radii } from '@/ui/tokens'

import { type IssueBadge, statusLabel } from './issueModel'

/** Spiking is filled, New is outlined: a spike needs attention now, a new issue needs a first look. */
export function IssueBadgePill({ badge }: { badge: IssueBadge }): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const spiking = badge === 'spiking'
    return (
        <View style={[styles.badge, spiking ? styles.filled : styles.outlined]} testID={`issue-badge-${badge}`}>
            {spiking ? <ArrowUpIcon size={11} color={colors.onAccent} strokeWidth={2.6} /> : null}
            <Text style={[styles.badgeText, spiking ? styles.filledText : styles.outlinedText]}>
                {spiking ? 'Spiking' : 'New'}
            </Text>
        </View>
    )
}

/** The web's status colors: amber active, green resolved, red suppressed. */
export function statusColor(status: string, colors: ThemeColors): string {
    switch (status as IssueStatusApi) {
        case 'active':
            return colors.yellow
        case 'resolved':
            return colors.diffGreen
        case 'suppressed':
            return colors.diffRed
        default:
            return colors.tertiary
    }
}

export function StatusChip({ status }: { status: string }): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <View style={styles.status} testID="issue-status-chip">
            <Dot color={statusColor(status, colors)} size={7} />
            <Text style={styles.statusText}>{statusLabel(status)}</Text>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    badge: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 3,
        height: 22,
        paddingHorizontal: 8,
        borderRadius: radii.pill,
        borderWidth: 1,
    },
    filled: {
        backgroundColor: colors.orange,
        borderColor: colors.orange,
    },
    outlined: {
        borderColor: colors.orangeLight,
    },
    badgeText: {
        fontSize: 12,
        fontWeight: '600',
    },
    filledText: {
        color: colors.onAccent,
    },
    outlinedText: {
        color: colors.orange,
    },
    status: {
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
    statusText: {
        fontSize: 13,
        fontWeight: '500',
        color: colors.ink,
    },
}))
