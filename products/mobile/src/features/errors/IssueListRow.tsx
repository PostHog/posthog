import { memo, type ReactElement } from 'react'
import { Text, View } from 'react-native'

import { Sparkline } from '@/ui/chart/Sparkline'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { type } from '@/ui/tokens'

import { AssigneeAvatar } from './AssigneeAvatar'
import { IssueBadgePill } from './IssueBadges'
import { agoPhrase, highlightStart, type IssueRow } from './issueModel'

const SPARK_WIDTH = 72
const SPARK_HEIGHT = 32

interface IssueListRowProps {
    row: IssueRow
    now: Date
    myName: string
    onOpen: (row: IssueRow) => void
}

function usersLabel(users: number): string {
    return `${users.toLocaleString()} ${users === 1 ? 'user' : 'users'}`
}

export const IssueListRow = memo(function IssueListRow({ row, now, myName, onOpen }: IssueListRowProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const from = highlightStart(row.volume, row.badge)
    const firstSeen = row.firstSeen ? agoPhrase(row.firstSeen, now) : null
    const meta = [usersLabel(row.users), firstSeen ? `first seen ${firstSeen}` : null].filter(Boolean).join(' · ')
    return (
        <Pressable44
            onPress={() => onOpen(row)}
            accessibilityRole="button"
            accessibilityLabel={[
                row.title,
                row.detail,
                row.badge === 'spiking' ? 'Spiking' : row.badge === 'new' ? 'New' : null,
                meta,
            ]
                .filter(Boolean)
                .join(', ')}
            pressedBackground={colors.pressed}
            style={styles.row}
            testID={`issue-row-${row.id}`}
        >
            <View style={styles.body}>
                <View style={styles.titleLine}>
                    <Text style={[styles.title, row.badge === 'new' && styles.newTitle]} numberOfLines={1}>
                        {row.title}
                    </Text>
                    {row.badge ? <IssueBadgePill badge={row.badge} /> : null}
                </View>
                {row.detail ? (
                    <Text style={styles.detail} numberOfLines={1}>
                        {row.detail}
                    </Text>
                ) : null}
                <View style={styles.meta}>
                    <AssigneeAvatar assignee={row.assignee} myName={myName} size={16} />
                    <Text style={styles.metaText} numberOfLines={1}>
                        {meta}
                    </Text>
                </View>
            </View>
            {row.volume.length > 1 ? (
                <Sparkline
                    values={row.volume}
                    highlightFrom={from ?? 0}
                    color={from === null ? colors.disabled : colors.orange}
                    width={SPARK_WIDTH}
                    height={SPARK_HEIGHT}
                    showDot={from !== null}
                />
            ) : null}
        </Pressable44>
    )
})

const useStyles = createStyles(({ colors }) => ({
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 14,
        paddingVertical: 13,
        paddingHorizontal: 2,
        borderBottomWidth: 1,
        borderBottomColor: colors.rowDivider,
    },
    body: {
        flex: 1,
        minWidth: 0,
        minHeight: 44,
        justifyContent: 'center',
        gap: 2,
    },
    titleLine: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
    },
    title: {
        ...type.rowTitle,
        fontWeight: '500',
        color: colors.ink,
        flexShrink: 1,
    },
    newTitle: {
        fontWeight: '700',
    },
    detail: {
        ...type.meta,
        color: colors.secondary,
    },
    meta: {
        marginTop: 2,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
    },
    metaText: {
        ...type.meta,
        color: colors.tertiary,
        flexShrink: 1,
    },
}))
