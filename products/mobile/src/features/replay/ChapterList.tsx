import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import { Eyebrow } from '@/ui/Eyebrow'
import { FlagIcon } from '@/ui/icons/FlagIcon'
import { MonoText } from '@/ui/MonoText'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, type } from '@/ui/tokens'

import { FrameImage } from './FrameImage'
import type { SummaryChapter } from './replayModel'
import { formatOffset } from './sessionAdapters'

interface ChapterListProps {
    observationId: string
    chapters: readonly SummaryChapter[]
    onOpen: (chapter: SummaryChapter) => void
}

export function ChapterList({ observationId, chapters, onOpen }: ChapterListProps): ReactElement | null {
    const colors = useColors()
    const styles = useStyles()
    if (chapters.length === 0) {
        return null
    }
    return (
        <View style={styles.section} testID="session-chapters">
            <View style={styles.header}>
                <Eyebrow>Chapters</Eyebrow>
                <Text style={styles.count}>{chapters.length}</Text>
            </View>
            {chapters.map((chapter) => (
                <Pressable44
                    key={chapter.index}
                    onPress={() => onOpen(chapter)}
                    accessibilityRole="button"
                    accessibilityLabel={`${chapter.title}, at ${formatOffset(chapter.startMs)}${chapter.isKeyMoment ? ', key moment' : ''}`}
                    pressedBackground={colors.sunken}
                    style={[styles.row, chapter.isKeyMoment && styles.keyRow]}
                    testID={`session-chapter-${chapter.index}`}
                >
                    <FrameImage
                        observationId={chapter.hasFrame ? observationId : null}
                        chapter={chapter.index}
                        style={styles.frame}
                    />
                    <View style={styles.body}>
                        <View style={styles.timeRow}>
                            {chapter.isKeyMoment ? <FlagIcon size={iconSizes.small} color={colors.orange} /> : null}
                            <MonoText color={chapter.isKeyMoment ? colors.orange : colors.secondary}>
                                {formatOffset(chapter.startMs)}
                            </MonoText>
                        </View>
                        <Text style={styles.title} numberOfLines={2}>
                            {chapter.title}
                        </Text>
                    </View>
                </Pressable44>
            ))}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    section: {
        marginTop: 28,
    },
    header: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: 8,
    },
    count: {
        ...type.meta,
        color: colors.tertiary,
    },
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        paddingVertical: 8,
        paddingHorizontal: 8,
        marginHorizontal: -8,
        borderRadius: 12,
        borderLeftWidth: 2,
        borderLeftColor: 'transparent',
    },
    keyRow: {
        borderLeftColor: colors.orange,
    },
    frame: {
        width: 96,
        height: 60,
    },
    body: {
        flex: 1,
        minWidth: 0,
        gap: 2,
    },
    timeRow: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 4,
    },
    title: {
        ...type.bodySmallStrong,
        color: colors.ink,
    },
}))
