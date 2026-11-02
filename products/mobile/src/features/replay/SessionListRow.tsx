import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import { Dot } from '@/ui/Dot'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { type } from '@/ui/tokens'

import { FrameImage } from './FrameImage'
import type { SessionListRow as Row } from './replayModel'
import { sessionRowMeta, sessionRowTitle } from './sessionAdapters'

interface SessionListRowProps {
    row: Row
    now: Date
    onOpen: (row: Row) => void
}

export function SessionListRow({ row, now, onOpen }: SessionListRowProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const title = sessionRowTitle(row)
    const meta = sessionRowMeta(row, now).join(' · ')
    const hasErrors = (row.consoleErrorCount ?? 0) > 0
    return (
        <Pressable44
            onPress={() => onOpen(row)}
            accessibilityRole="button"
            accessibilityLabel={`${title}. ${meta}`}
            pressedBackground={colors.sunken}
            style={styles.row}
            testID={`session-row-${row.sessionId}`}
        >
            <FrameImage observationId={row.thumbnailObservationId} chapter={null} style={styles.thumb} />
            <View style={styles.body}>
                <Text style={[styles.title, row.title === null && styles.titlePlain]} numberOfLines={2}>
                    {title}
                </Text>
                <View style={styles.metaRow}>
                    {hasErrors ? <Dot color={colors.orange} /> : null}
                    <Text style={styles.meta} numberOfLines={2}>
                        {meta}
                    </Text>
                </View>
            </View>
        </Pressable44>
    )
}

const useStyles = createStyles(({ colors }) => ({
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 14,
        paddingVertical: 14,
        borderBottomWidth: 1,
        borderBottomColor: colors.rowDivider,
    },
    thumb: {
        width: 80,
        height: 50,
    },
    body: {
        flex: 1,
        minWidth: 0,
        gap: 4,
    },
    title: {
        ...type.rowTitle,
        color: colors.ink,
    },
    titlePlain: {
        fontWeight: '400',
    },
    metaRow: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
    },
    meta: {
        ...type.meta,
        color: colors.secondary,
        flexShrink: 1,
    },
}))
