import { type ReactElement, type ReactNode, useEffect, useMemo, useRef } from 'react'
import { FlatList, Image, Switch, Text, View } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'

import { BottomSheet } from '@/ui/BottomSheet'
import { CopyIcon } from '@/ui/icons/CopyIcon'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { EyeOffIcon } from '@/ui/icons/EyeOffIcon'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { SegmentedPill } from '@/ui/SegmentedPill'
import { createStyles, useColors } from '@/ui/theme'
import { fonts, iconSizes, radii, type } from '@/ui/tokens'
import { useSceneDimensions } from '@/ui/useSceneDimensions'

import { useFrameUrl } from '../hooks'
import { formatOffset } from '../sessionAdapters'
import { speedLabel } from './FeedRail'
import {
    type FeedEvent,
    type FeedItem,
    type FeedSettings,
    type FeedSource,
    type FeedTimeline,
    SPEED_PRESETS,
} from './feedModel'
import { tickColors } from './feedStyle'
import { holdRateFor } from './holdLock'

export const SOURCE_LABELS: Record<FeedSource, string> = {
    highlights: 'Highlights',
    rage: 'Rage clicks',
    errors: 'Errors',
    newest: 'Newest',
}

interface SettingsSheetProps {
    visible: boolean
    /** `speed` is the one playing: a locked hold speed shows as the selected one. */
    settings: FeedSettings
    /** A pull locked the speed. A hold then unlocks instead of speeding up, so the hold hint does not apply. */
    locked: boolean
    onChange: (patch: Partial<FeedSettings>) => void
    onClose: () => void
}

function holdHint(speed: number): string | null {
    const rate = holdRateFor(speed)
    return rate === null ? null : `Hold the video for ${rate}x. Pull down while you hold to lock it.`
}

export function FeedSettingsSheet({
    visible,
    settings,
    locked,
    onChange,
    onClose,
}: SettingsSheetProps): ReactElement | null {
    const styles = useStyles()
    const hint = locked ? null : holdHint(settings.speed)
    return (
        <BottomSheet visible={visible} onClose={onClose} accessibilityLabel="Playback" testID="feed-settings-sheet">
            <Text style={styles.sheetTitle}>Playback</Text>
            <Section label="Speed">
                <SegmentedPill
                    height={40}
                    segments={SPEED_PRESETS.map((speed) => ({
                        key: String(speed),
                        accessibilityLabel: `${speed} times`,
                        accessibilityRole: 'radio',
                        selected: settings.speed === speed,
                        onPress: () => onChange({ speed }),
                        testID: `feed-speed-${speed}`,
                        children: <Text style={styles.segmentText}>{speedLabel(speed)}</Text>,
                    }))}
                />
                {hint ? <Text style={styles.hint}>{hint}</Text> : null}
            </Section>
            <SwitchRow
                label="Skip inactivity"
                value={settings.skipInactivity}
                onChange={(skipInactivity) => onChange({ skipInactivity })}
                testID="feed-skip-inactivity"
            />
            <SwitchRow
                label="Autoplay next"
                value={settings.autoplayNext}
                onChange={(autoplayNext) => onChange({ autoplayNext })}
                testID="feed-autoplay"
            />
        </BottomSheet>
    )
}

function SwitchRow({
    label,
    value,
    onChange,
    testID,
}: {
    label: string
    value: boolean
    onChange: (value: boolean) => void
    testID: string
}): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    return (
        <View style={styles.switchRow}>
            <Text style={[styles.rowLabel, styles.switchText]}>{label}</Text>
            <Switch
                value={value}
                onValueChange={onChange}
                trackColor={{ true: colors.switchOn, false: colors.switchOff }}
                thumbColor={colors.white}
                accessibilityLabel={label}
                testID={testID}
            />
        </View>
    )
}

function Section({ label, children }: { label: string; children: ReactNode }): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.section}>
            <Text style={styles.sectionLabel}>{label}</Text>
            {children}
        </View>
    )
}

interface InfoSheetProps {
    visible: boolean
    item: FeedItem | null
    timeline: FeedTimeline | null
    /** Where playback was when Info opened: the event list opens scrolled to the event at or before it. */
    nowSeconds: number
    onSeek: (seconds: number) => void
    onOpenWeb: (() => void) | null
    onNotInterested: () => void
    onClose: () => void
}

const INFO_EVENT_KINDS: ReadonlySet<FeedEvent['kind']> = new Set([
    'pageview',
    'rageclick',
    'deadclick',
    'exception',
    'custom',
])

export function FeedInfoSheet({
    visible,
    item,
    timeline,
    nowSeconds,
    onSeek,
    onOpenWeb,
    onNotInterested,
    onClose,
}: InfoSheetProps): ReactElement | null {
    const styles = useStyles()
    const colors = useColors()
    const { height } = useSceneDimensions()
    const scroll = useMemo(() => Gesture.Native(), [])
    const summary = item?.summary ?? null
    const events = (timeline?.events ?? []).filter((event) => INFO_EVENT_KINDS.has(event.kind))
    const currentIndex = events.reduce((found, event, index) => (event.seconds <= nowSeconds + 0.5 ? index : found), -1)
    const listRef = useRef<FlatList<FeedEvent>>(null)
    const layout = useRef({ header: 0, viewport: 0, firstRow: 0, scrolled: false })
    const scrollToCurrent = (): void => {
        const { viewport, header, firstRow, scrolled } = layout.current
        if (currentIndex < 0 || scrolled || !viewport || !header || !firstRow) {
            return
        }
        layout.current.scrolled = true
        if (header + (currentIndex + 1) * firstRow > viewport) {
            listRef.current?.scrollToIndex({ index: currentIndex, animated: false, viewPosition: 0.5 })
        }
    }
    useEffect(() => {
        if (!visible) {
            layout.current = { header: 0, viewport: 0, firstRow: 0, scrolled: false }
        }
    }, [visible])
    const seek = (seconds: number): void => {
        onSeek(seconds)
        onClose()
    }
    return (
        <BottomSheet
            visible={visible}
            onClose={onClose}
            scrollGesture={scroll}
            accessibilityLabel="Recording info"
            testID="feed-info-sheet"
        >
            <GestureDetector gesture={scroll}>
                <FlatList
                    ref={listRef}
                    data={events}
                    keyExtractor={(event) => event.key}
                    initialNumToRender={12}
                    windowSize={5}
                    onLayout={(event) => {
                        layout.current.viewport = event.nativeEvent.layout.height
                        scrollToCurrent()
                    }}
                    onScrollToIndexFailed={({ index, averageItemLength }) => {
                        const { header, viewport } = layout.current
                        listRef.current?.scrollToOffset({
                            offset: Math.max(0, header + averageItemLength * (index + 0.5) - viewport / 2),
                            animated: false,
                        })
                    }}
                    style={{ maxHeight: height * 0.64 }}
                    contentContainerStyle={styles.infoContent}
                    ListHeaderComponent={
                        <View
                            onLayout={(event) => {
                                layout.current.header = event.nativeEvent.layout.height
                                scrollToCurrent()
                            }}
                        >
                            <Text style={styles.sheetTitle}>Recording</Text>
                            <Text style={styles.infoPerson} numberOfLines={1}>
                                {item ? item.recording.personLabel : ''}
                            </Text>
                            <Section label="Summary">
                                {summary?.title ? <Text style={styles.summaryTitle}>{summary.title}</Text> : null}
                                <Text style={summary?.text ? styles.summaryText : styles.hint}>
                                    {summary?.text ?? 'No summary yet. The events below come from the recording.'}
                                </Text>
                            </Section>
                            {summary && summary.chapters.length > 0 ? (
                                <Section label="Chapters">
                                    <View style={styles.group}>
                                        {summary.chapters.map((chapter, position) => (
                                            <Pressable44
                                                key={chapter.index}
                                                onPress={() => seek(chapter.startMs / 1000)}
                                                accessibilityLabel={`${chapter.title}, at ${formatOffset(chapter.startMs)}`}
                                                pressedBackground={colors.pressed}
                                                hitSlop={0}
                                                style={[styles.chapterRow, position > 0 && styles.rowDivider]}
                                                testID={`feed-info-chapter-${position}`}
                                            >
                                                <ChapterFrame
                                                    observationId={summary.observationId}
                                                    chapter={chapter.index}
                                                />
                                                <View style={styles.chapterText}>
                                                    <Text style={styles.time}>{formatOffset(chapter.startMs)}</Text>
                                                    <Text style={styles.chapterTitle} numberOfLines={2}>
                                                        {chapter.title}
                                                    </Text>
                                                </View>
                                                {chapter.isKeyMoment ? (
                                                    <View
                                                        style={[styles.keyMark, { backgroundColor: tickColors.key }]}
                                                    />
                                                ) : null}
                                            </Pressable44>
                                        ))}
                                    </View>
                                </Section>
                            ) : null}
                            <Text style={[styles.sectionLabel, styles.eventsLabel]}>{`Events · ${events.length}`}</Text>
                        </View>
                    }
                    ListEmptyComponent={
                        <Text style={[styles.hint, styles.group, styles.emptyEvents]}>Loading events…</Text>
                    }
                    renderItem={({ item: event, index }) => (
                        <Pressable44
                            onPress={() => seek(Math.max(0, event.seconds - 1))}
                            accessibilityLabel={`${event.label}, at ${formatOffset(event.seconds * 1000)}`}
                            pressedBackground={colors.pressed}
                            hitSlop={0}
                            style={[
                                styles.eventRow,
                                styles.eventGroupRow,
                                index === 0 ? styles.eventGroupStart : styles.rowDivider,
                                index === events.length - 1 && styles.eventGroupEnd,
                                index === currentIndex && styles.eventRowCurrent,
                            ]}
                            accessibilityState={{ selected: index === currentIndex }}
                            onLayout={
                                index === 0
                                    ? (event) => {
                                          layout.current.firstRow = event.nativeEvent.layout.height
                                          scrollToCurrent()
                                      }
                                    : undefined
                            }
                            testID={`feed-info-event-${index}`}
                        >
                            <Text style={styles.time}>{formatOffset(event.seconds * 1000)}</Text>
                            <EventGlyph kind={event.kind} />
                            <Text
                                style={[
                                    styles.eventLabel,
                                    (event.kind === 'rageclick' || event.kind === 'exception') && {
                                        color: colors.orange,
                                    },
                                ]}
                                numberOfLines={2}
                            >
                                {event.label}
                            </Text>
                        </Pressable44>
                    )}
                />
            </GestureDetector>
            <View style={styles.infoFooter}>
                <Pressable44
                    onPress={onNotInterested}
                    accessibilityLabel="Not interested"
                    style={styles.footerButton}
                    pressedBackground={colors.pressed}
                    testID="feed-info-not-interested"
                >
                    <EyeOffIcon size={iconSizes.inline} color={colors.ink} />
                    <Text style={styles.footerText}>Not interested</Text>
                </Pressable44>
                {onOpenWeb ? (
                    <Pressable44
                        onPress={onOpenWeb}
                        accessibilityRole="link"
                        accessibilityLabel="Open in PostHog"
                        style={styles.footerButton}
                        pressedBackground={colors.pressed}
                        testID="feed-info-open-web"
                    >
                        <ExternalLinkIcon size={iconSizes.inline} color={colors.ink} />
                        <Text style={styles.footerText}>Open in PostHog</Text>
                    </Pressable44>
                ) : null}
            </View>
        </BottomSheet>
    )
}

interface ShareSheetProps {
    visible: boolean
    seconds: number
    onCopyLink: () => void
    onOpenWeb: (() => void) | null
    onClose: () => void
}

/** The time is fixed when the sheet opens, so the copied link matches the time it shows. */
export function FeedShareSheet({
    visible,
    seconds,
    onCopyLink,
    onOpenWeb,
    onClose,
}: ShareSheetProps): ReactElement | null {
    const styles = useStyles()
    const colors = useColors()
    return (
        <BottomSheet visible={visible} onClose={onClose} accessibilityLabel="Share" testID="feed-share-sheet">
            <Text style={styles.sheetTitle}>Share</Text>
            <View style={styles.shareGroup}>
                <Pressable44
                    onPress={onCopyLink}
                    accessibilityLabel={`Copy link at ${formatOffset(seconds * 1000)}`}
                    pressedBackground={colors.pressed}
                    hitSlop={0}
                    style={styles.shareRow}
                    testID="feed-share-copy"
                >
                    <CopyIcon size={20} color={colors.ink} />
                    <View style={styles.shareText}>
                        <Text style={styles.shareLabel}>Copy link</Text>
                        <Text style={styles.shareSub}>{`At ${formatOffset(seconds * 1000)}`}</Text>
                    </View>
                </Pressable44>
                {onOpenWeb ? (
                    <Pressable44
                        onPress={onOpenWeb}
                        accessibilityRole="link"
                        accessibilityLabel="Open in PostHog"
                        pressedBackground={colors.pressed}
                        hitSlop={0}
                        style={[styles.shareRow, styles.rowDivider]}
                        testID="feed-share-open-web"
                    >
                        <ExternalLinkIcon size={20} color={colors.ink} />
                        <View style={styles.shareText}>
                            <Text style={styles.shareLabel}>Open in PostHog</Text>
                        </View>
                    </Pressable44>
                ) : null}
            </View>
        </BottomSheet>
    )
}

function ChapterFrame({ observationId, chapter }: { observationId: string; chapter: number }): ReactElement {
    const styles = useStyles()
    const frame = useFrameUrl(observationId, chapter)
    return (
        <View style={styles.frame}>
            {frame.data ? (
                <Image source={{ uri: frame.data }} style={styles.frameImage} accessibilityIgnoresInvertColors />
            ) : null}
        </View>
    )
}

function EventGlyph({ kind }: { kind: FeedEvent['kind'] }): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    if (kind === 'rageclick' || kind === 'deadclick') {
        return <View style={[styles.glyphDot, { backgroundColor: tickColors.rage }]} />
    }
    if (kind === 'exception') {
        return <WarningIcon size={14} color={colors.orange} />
    }
    if (kind === 'custom') {
        return <View style={[styles.glyphDot, { backgroundColor: tickColors.custom }]} />
    }
    return <View style={[styles.glyphDot, { backgroundColor: colors.border }]} />
}

const useStyles = createStyles(({ colors }) => ({
    sheetTitle: {
        ...type.sheetTitle,
        color: colors.ink,
        marginTop: 12,
        marginBottom: 6,
    },
    sheetLead: {
        ...type.bodySmall,
        color: colors.secondary,
        marginBottom: 14,
    },
    section: {
        marginTop: 16,
        gap: 8,
    },
    sectionLabel: {
        ...type.eyebrow,
        color: colors.secondary,
        textTransform: 'uppercase',
    },
    segmentText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
    hint: {
        ...type.meta,
        color: colors.secondary,
    },
    switchRow: {
        marginTop: 18,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
    },
    switchText: {
        flex: 1,
        gap: 2,
    },
    rowLabel: {
        ...type.bodyStrong,
        color: colors.ink,
    },
    infoContent: {
        paddingBottom: 12,
    },
    infoPerson: {
        ...type.bodySmallStrong,
        color: colors.ink,
        marginTop: 2,
    },
    summaryTitle: {
        ...type.bodySmallStrong,
        color: colors.ink,
        marginBottom: 4,
    },
    summaryText: {
        ...type.bodySmall,
        color: colors.ink,
    },
    infoFooter: {
        flexDirection: 'row',
        gap: 10,
        paddingTop: 12,
    },
    footerButton: {
        flex: 1,
        height: 46,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        borderRadius: radii.option,
        borderWidth: 1,
        borderColor: colors.border,
    },
    footerText: {
        ...type.bodySmallStrong,
        color: colors.ink,
    },
    shareGroup: {
        borderRadius: radii.option,
        borderWidth: 1,
        borderColor: colors.border,
        overflow: 'hidden',
    },
    shareRow: {
        minHeight: 58,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        paddingHorizontal: 16,
    },
    shareText: {
        flex: 1,
        gap: 2,
    },
    shareLabel: {
        ...type.bodySmallStrong,
        color: colors.ink,
    },
    shareSub: {
        ...type.meta,
        color: colors.secondary,
    },
    group: {
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
        overflow: 'hidden',
    },
    rowDivider: {
        borderTopWidth: 1,
        borderTopColor: colors.rowDivider,
    },
    chapterRow: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        padding: 10,
    },
    frame: {
        width: 96,
        height: 60,
        borderRadius: radii.tile,
        overflow: 'hidden',
        backgroundColor: colors.sunken,
        borderWidth: 1,
        borderColor: colors.hairline,
    },
    frameImage: {
        width: '100%',
        height: '100%',
    },
    chapterText: {
        flex: 1,
        gap: 2,
    },
    chapterTitle: {
        ...type.bodySmallStrong,
        color: colors.ink,
    },
    keyMark: {
        width: 8,
        height: 8,
        borderRadius: 4,
    },
    time: {
        fontFamily: fonts.mono,
        fontSize: 12,
        color: colors.secondary,
        minWidth: 38,
    },
    eventsLabel: { marginTop: 18, marginBottom: 8 },
    eventGroupRow: {
        borderLeftWidth: 1,
        borderRightWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
    },
    eventGroupStart: {
        borderTopWidth: 1,
        borderTopLeftRadius: radii.card,
        borderTopRightRadius: radii.card,
    },
    eventGroupEnd: {
        borderBottomWidth: 1,
        borderBottomLeftRadius: radii.card,
        borderBottomRightRadius: radii.card,
    },
    eventRow: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
        paddingVertical: 11,
        paddingHorizontal: 12,
    },
    eventRowCurrent: {
        backgroundColor: colors.pressed,
        borderLeftWidth: 3,
        borderLeftColor: colors.orange,
    },
    eventLabel: {
        ...type.bodySmall,
        flex: 1,
        color: colors.ink,
    },
    emptyEvents: {
        padding: 12,
    },
    glyphDot: {
        width: 8,
        height: 8,
        borderRadius: 4,
        marginHorizontal: 3,
    },
    webRow: {
        marginTop: 18,
        height: 44,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
    },
    webText: {
        ...type.bodySmallStrong,
        color: colors.ink,
    },
}))
