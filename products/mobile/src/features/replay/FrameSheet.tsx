import { type ReactElement, useRef } from 'react'
import { Text, useWindowDimensions, View } from 'react-native'

import { BottomSheet } from '@/ui/BottomSheet'
import { ChevronLeftIcon } from '@/ui/icons/ChevronLeftIcon'
import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { CloseIcon } from '@/ui/icons/CloseIcon'
import { FlagIcon } from '@/ui/icons/FlagIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { SegmentedPill } from '@/ui/SegmentedPill'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'

import { FrameImage } from './FrameImage'
import type { SummaryChapter } from './replayModel'
import { formatOffset } from './sessionAdapters'

/** The analysis video is 16:10, so its frames are too. */
const FRAME_ASPECT = 16 / 10
const SHEET_PADDING = 20

interface FrameSheetProps {
    observationId: string
    chapters: readonly SummaryChapter[]
    /** Index into `chapters` of the chapter shown, or null when the sheet is closed. */
    position: number | null
    onChangePosition: (position: number) => void
    onClose: () => void
}

export function FrameSheet({
    observationId,
    chapters,
    position,
    onChangePosition,
    onClose,
}: FrameSheetProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const { width } = useWindowDimensions()
    // The last chapter stays drawn while the sheet slides out.
    const shown = useRef<number>(0)
    if (position !== null) {
        shown.current = position
    }
    const index = shown.current
    const chapter = chapters[index]
    const frameWidth = width - SHEET_PADDING * 2
    return (
        <BottomSheet
            visible={position !== null}
            onClose={onClose}
            paddingHorizontal={SHEET_PADDING}
            accessibilityLabel="Chapter frame"
            testID="session-frame-sheet"
        >
            {chapter ? (
                <View style={styles.body}>
                    <View style={styles.header}>
                        <Text style={styles.title} accessibilityRole="header">
                            {`Frame at ${formatOffset(chapter.frameMs ?? chapter.startMs)}`}
                        </Text>
                        <Pressable44
                            onPress={onClose}
                            accessibilityLabel="Close"
                            pressedBackground={colors.sunken}
                            style={styles.close}
                            testID="session-frame-close"
                        >
                            <CloseIcon size={iconSizes.control} />
                        </Pressable44>
                    </View>
                    <FrameImage
                        observationId={chapter.hasFrame ? observationId : null}
                        chapter={chapter.index}
                        style={{ width: frameWidth, height: Math.round(frameWidth / FRAME_ASPECT) }}
                        accessibilityLabel={`Frame of ${chapter.title}`}
                    />
                    <View style={styles.captionRow}>
                        <View style={styles.caption}>
                            <Text style={styles.chapterTitle}>{chapter.title}</Text>
                            <Text style={styles.meta}>
                                {`Chapter ${index + 1} of ${chapters.length} · ${formatOffset(chapter.startMs)}`}
                            </Text>
                        </View>
                        {chapter.isKeyMoment ? (
                            <View style={styles.keyChip}>
                                <FlagIcon size={iconSizes.small} color={colors.orange} />
                                <Text style={styles.keyText}>Key moment</Text>
                            </View>
                        ) : null}
                    </View>
                    {chapters.length > 1 ? (
                        <SegmentedPill
                            style={styles.pager}
                            height={46}
                            segmentWidth={52}
                            segments={[
                                {
                                    key: 'previous',
                                    accessibilityLabel: 'Previous chapter',
                                    onPress: () => onChangePosition(index - 1),
                                    disabled: index === 0,
                                    testID: 'session-frame-previous',
                                    children: <ChevronLeftIcon size={iconSizes.control} />,
                                },
                                {
                                    key: 'next',
                                    accessibilityLabel: 'Next chapter',
                                    onPress: () => onChangePosition(index + 1),
                                    disabled: index === chapters.length - 1,
                                    testID: 'session-frame-next',
                                    children: <ChevronRightIcon size={iconSizes.control} />,
                                },
                            ]}
                        />
                    ) : null}
                    <Text style={styles.note}>Frames can show text that the recording did not mask.</Text>
                </View>
            ) : null}
        </BottomSheet>
    )
}

const useStyles = createStyles(({ colors }) => ({
    body: {
        gap: 14,
        paddingBottom: 8,
    },
    header: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginTop: 8,
    },
    title: {
        ...type.sheetTitle,
        color: colors.ink,
    },
    close: {
        width: 44,
        height: 44,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        alignItems: 'center',
        justifyContent: 'center',
    },
    captionRow: {
        flexDirection: 'row',
        alignItems: 'flex-start',
        gap: 12,
    },
    caption: {
        flex: 1,
        minWidth: 0,
    },
    chapterTitle: {
        ...type.rowTitle,
        color: colors.ink,
    },
    meta: {
        ...type.meta,
        color: colors.secondary,
        marginTop: 2,
    },
    keyChip: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
        height: 32,
        paddingHorizontal: 12,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.orange,
    },
    keyText: {
        ...type.meta,
        fontWeight: '600',
        color: colors.orange,
    },
    pager: {
        alignSelf: 'flex-start',
    },
    note: {
        ...type.meta,
        color: colors.tertiary,
    },
}))
