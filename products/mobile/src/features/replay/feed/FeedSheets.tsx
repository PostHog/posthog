import { type ReactElement, type ReactNode, useMemo } from 'react'
import { Image, ScrollView, Switch, Text, View } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'

import { BottomSheet } from '@/ui/BottomSheet'
import { ErrorTriangleIcon } from '@/ui/icons/ErrorTriangleIcon'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { FlagIcon } from '@/ui/icons/FlagIcon'
import { RecordingIcon } from '@/ui/icons/RecordingIcon'
import { SparklesIcon } from '@/ui/icons/SparklesIcon'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { OptionCard, type OptionCardItem } from '@/ui/OptionCard'
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
    LEAD_IN_PRESETS,
    MOMENT_LENGTH_PRESETS,
    SPEED_PRESETS,
} from './feedModel'
import { tickColors } from './feedStyle'

export const SOURCE_LABELS: Record<FeedSource, string> = {
    newest: 'Newest',
    worth: 'Worth watching',
    rage: 'Rage clicks',
    errors: 'Errors',
}

const SOURCE_OPTIONS: readonly OptionCardItem<FeedSource>[] = [
    { key: 'newest', label: 'Newest', description: 'Finished sessions, newest first', Icon: RecordingIcon },
    { key: 'worth', label: 'Worth watching', description: 'The most active sessions first', Icon: SparklesIcon },
    { key: 'rage', label: 'Rage clicks', description: 'Sessions where someone rage clicked', Icon: FlagIcon },
    { key: 'errors', label: 'Errors', description: 'Sessions with an exception', Icon: ErrorTriangleIcon },
]

interface SourceSheetProps {
    visible: boolean
    source: FeedSource
    onSelect: (source: FeedSource) => void
    onClose: () => void
}

export function FeedSourceSheet({ visible, source, onSelect, onClose }: SourceSheetProps): ReactElement | null {
    const styles = useStyles()
    return (
        <BottomSheet visible={visible} onClose={onClose} accessibilityLabel="Show" testID="feed-source-sheet">
            <Text style={styles.sheetTitle}>Show</Text>
            <Text style={styles.sheetLead}>Each source plays its own moments: rage clicks, errors or key moments.</Text>
            <OptionCard
                options={SOURCE_OPTIONS}
                selected={source}
                onSelect={(key) => {
                    onSelect(key)
                    onClose()
                }}
                testIDPrefix="feed-source"
            />
        </BottomSheet>
    )
}

interface SettingsSheetProps {
    visible: boolean
    settings: FeedSettings
    onChange: (patch: Partial<FeedSettings>) => void
    onClose: () => void
}

export function FeedSettingsSheet({ visible, settings, onChange, onClose }: SettingsSheetProps): ReactElement | null {
    const styles = useStyles()
    const colors = useColors()
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
                <Text style={styles.hint}>Press and hold the video to play at 4× for as long as you hold.</Text>
            </Section>
            <View style={styles.switchRow}>
                <View style={styles.switchText}>
                    <Text style={styles.rowLabel}>Autoplay next</Text>
                    <Text style={styles.hint}>When one ends, the next starts after 3 seconds.</Text>
                </View>
                <Switch
                    value={settings.autoplayNext}
                    onValueChange={(autoplayNext) => onChange({ autoplayNext })}
                    trackColor={{ true: colors.switchOn, false: colors.switchOff }}
                    thumbColor={colors.white}
                    accessibilityLabel="Autoplay next"
                    testID="feed-autoplay"
                />
            </View>
            <Section label="A session starts at">
                <SegmentedPill
                    height={40}
                    segments={(['key', 'beginning'] as const).map((startAt) => ({
                        key: startAt,
                        accessibilityLabel: startAt === 'key' ? 'Key moment' : 'Beginning',
                        accessibilityRole: 'radio',
                        selected: settings.startAt === startAt,
                        onPress: () => onChange({ startAt }),
                        children: (
                            <Text style={styles.segmentText}>{startAt === 'key' ? 'Key moment' : 'Beginning'}</Text>
                        ),
                    }))}
                />
            </Section>
            <Section label="Lead-in before a moment">
                <SegmentedPill
                    height={40}
                    segments={LEAD_IN_PRESETS.map((leadInSeconds) => ({
                        key: String(leadInSeconds),
                        accessibilityLabel: `${leadInSeconds} seconds`,
                        accessibilityRole: 'radio',
                        selected: settings.leadInSeconds === leadInSeconds,
                        onPress: () => onChange({ leadInSeconds }),
                        children: <Text style={styles.segmentText}>{`${leadInSeconds} s`}</Text>,
                    }))}
                />
            </Section>
            <Section label="Moment length">
                <SegmentedPill
                    height={40}
                    segments={MOMENT_LENGTH_PRESETS.map((momentSeconds) => ({
                        key: String(momentSeconds),
                        accessibilityLabel: `${momentSeconds} seconds`,
                        accessibilityRole: 'radio',
                        selected: settings.momentSeconds === momentSeconds,
                        onPress: () => onChange({ momentSeconds }),
                        children: <Text style={styles.segmentText}>{`${momentSeconds} s`}</Text>,
                    }))}
                />
            </Section>
            <Section label="Phone sessions">
                <SegmentedPill
                    height={40}
                    segments={(['fill', 'whole'] as const).map((phoneFit) => ({
                        key: phoneFit,
                        accessibilityLabel: phoneFit === 'fill' ? 'Fill the screen' : 'Whole screen',
                        accessibilityRole: 'radio',
                        selected: settings.phoneFit === phoneFit,
                        onPress: () => onChange({ phoneFit }),
                        testID: `feed-phone-fit-${phoneFit}`,
                        children: (
                            <Text style={styles.segmentText}>{phoneFit === 'fill' ? 'Fill' : 'Whole screen'}</Text>
                        ),
                    }))}
                />
            </Section>
            <Text style={styles.footnote}>
                Videos are prepared on the server when you stay on a session or press Play. Each one counts toward your
                team's monthly video limit.
            </Text>
        </BottomSheet>
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
    onSeek: (seconds: number) => void
    onOpenWeb: (() => void) | null
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
    onSeek,
    onOpenWeb,
    onClose,
}: InfoSheetProps): ReactElement | null {
    const styles = useStyles()
    const colors = useColors()
    const { height } = useSceneDimensions()
    const scroll = useMemo(() => Gesture.Native(), [])
    const summary = item?.summary ?? null
    const events = (timeline?.events ?? []).filter((event) => INFO_EVENT_KINDS.has(event.kind))
    const seek = (seconds: number): void => {
        onSeek(seconds)
        onClose()
    }
    return (
        <BottomSheet
            visible={visible}
            onClose={onClose}
            scrollGesture={scroll}
            accessibilityLabel="Session info"
            testID="feed-info-sheet"
        >
            <GestureDetector gesture={scroll}>
                <ScrollView style={{ maxHeight: height * 0.7 }} contentContainerStyle={styles.infoContent}>
                    <Text style={styles.sheetTitle} numberOfLines={3}>
                        {summary?.title ?? 'Session'}
                    </Text>
                    <Text style={styles.infoMeta}>{item ? item.recording.personLabel : ''}</Text>
                    {summary?.text ? <Text style={styles.summaryText}>{summary.text}</Text> : null}
                    {!summary ? (
                        <Text style={styles.hint}>No summary yet. The events below come from the recording.</Text>
                    ) : null}
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
                                        <ChapterFrame observationId={summary.observationId} chapter={chapter.index} />
                                        <View style={styles.chapterText}>
                                            <Text style={styles.time}>{formatOffset(chapter.startMs)}</Text>
                                            <Text style={styles.chapterTitle} numberOfLines={2}>
                                                {chapter.title}
                                            </Text>
                                        </View>
                                        {chapter.isKeyMoment ? (
                                            <View style={[styles.keyMark, { backgroundColor: tickColors.key }]} />
                                        ) : null}
                                    </Pressable44>
                                ))}
                            </View>
                        </Section>
                    ) : null}
                    <Section label={`Events · ${events.length}`}>
                        <View style={styles.group}>
                            {events.length === 0 ? (
                                <Text style={[styles.hint, styles.emptyEvents]}>Loading events…</Text>
                            ) : (
                                events.map((event, position) => (
                                    <Pressable44
                                        key={event.key}
                                        onPress={() => seek(Math.max(0, event.seconds - 1))}
                                        accessibilityLabel={`${event.label}, at ${formatOffset(event.seconds * 1000)}`}
                                        pressedBackground={colors.pressed}
                                        hitSlop={0}
                                        style={[styles.eventRow, position > 0 && styles.rowDivider]}
                                        testID={`feed-info-event-${position}`}
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
                                ))
                            )}
                        </View>
                    </Section>
                    {onOpenWeb ? (
                        <Pressable44
                            onPress={onOpenWeb}
                            accessibilityRole="link"
                            accessibilityLabel="Open in PostHog"
                            style={styles.webRow}
                            testID="feed-info-open-web"
                        >
                            <Text style={styles.webText}>Open in PostHog</Text>
                            <ExternalLinkIcon size={iconSizes.inline} color={colors.secondary} />
                        </Pressable44>
                    ) : null}
                </ScrollView>
            </GestureDetector>
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
    footnote: {
        ...type.meta,
        color: colors.tertiary,
        marginTop: 18,
        marginBottom: 4,
    },
    infoContent: {
        paddingBottom: 12,
    },
    infoMeta: {
        ...type.meta,
        color: colors.secondary,
    },
    summaryText: {
        ...type.bodySmall,
        color: colors.ink,
        marginTop: 10,
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
    eventRow: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
        paddingVertical: 11,
        paddingHorizontal: 12,
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
