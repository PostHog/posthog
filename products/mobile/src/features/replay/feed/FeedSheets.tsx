import { type ReactElement, type ReactNode, useMemo } from 'react'
import { Image, ScrollView, Switch, Text, View } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'

import { BottomSheet } from '@/ui/BottomSheet'
import { CopyIcon } from '@/ui/icons/CopyIcon'
import { ErrorTriangleIcon } from '@/ui/icons/ErrorTriangleIcon'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { EyeOffIcon } from '@/ui/icons/EyeOffIcon'
import { FlagIcon } from '@/ui/icons/FlagIcon'
import { LockIcon } from '@/ui/icons/LockIcon'
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
    type FeedUnit,
    LEAD_IN_PRESETS,
    MOMENT_LENGTH_PRESETS,
    SPEED_PRESETS,
} from './feedModel'
import { tickColors } from './feedStyle'
import { type HoldLock, holdRateFor } from './holdLock'

export const SOURCE_LABELS: Record<FeedSource, string> = {
    highlights: 'Highlights',
    rage: 'Rage clicks',
    errors: 'Errors',
    newest: 'Newest',
}

const SOURCE_OPTIONS: readonly OptionCardItem<FeedSource>[] = [
    { key: 'highlights', label: 'Highlights', description: 'Ranked by Replay Vision', Icon: SparklesIcon },
    { key: 'rage', label: 'Rage clicks', description: 'Recordings with a rage click', Icon: FlagIcon },
    { key: 'errors', label: 'Errors', description: 'Recordings with an exception', Icon: ErrorTriangleIcon },
    { key: 'newest', label: 'Newest', description: 'Finished recordings, newest first', Icon: RecordingIcon },
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
        <BottomSheet visible={visible} onClose={onClose} accessibilityLabel="Sources" testID="feed-source-sheet">
            <Text style={styles.sheetTitle}>Sources</Text>
            <Text style={styles.sheetLead}>Choose what the feed plays.</Text>
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
    unit: FeedUnit
    lock: HoldLock | null
    /** The MP4 player renders exports, so only it shows what a render costs. */
    showsExportCost: boolean
    onChange: (patch: Partial<FeedSettings>) => void
    onUnit: (unit: FeedUnit) => void
    onUnlock: () => void
    onClose: () => void
}

function holdHint(speed: number): string {
    const rate = holdRateFor(speed)
    return rate === null
        ? 'Hold has no effect at 4x or faster.'
        : `Hold the video for ${rate}x. Pull down while you hold to lock it.`
}

export function FeedSettingsSheet({
    visible,
    settings,
    unit,
    lock,
    showsExportCost,
    onChange,
    onUnit,
    onUnlock,
    onClose,
}: SettingsSheetProps): ReactElement | null {
    const styles = useStyles()
    const colors = useColors()
    const { height } = useSceneDimensions()
    const scroll = useMemo(() => Gesture.Native(), [])
    return (
        <BottomSheet
            visible={visible}
            onClose={onClose}
            scrollGesture={scroll}
            accessibilityLabel="Playback"
            testID="feed-settings-sheet"
        >
            <GestureDetector gesture={scroll}>
                <ScrollView style={{ maxHeight: height * 0.72 }} contentContainerStyle={styles.infoContent}>
                    <Text style={styles.sheetTitle}>Playback</Text>
                    <Section label="Feed plays">
                        <SegmentedPill
                            height={40}
                            segments={(['moment', 'session'] as const).map((option) => ({
                                key: option,
                                accessibilityLabel: option === 'moment' ? 'Moments' : 'Whole recordings',
                                accessibilityRole: 'radio',
                                selected: unit === option,
                                onPress: () => onUnit(option),
                                testID: `feed-plays-${option}`,
                                children: (
                                    <Text style={styles.segmentText}>
                                        {option === 'moment' ? 'Moments' : 'Whole recordings'}
                                    </Text>
                                ),
                            }))}
                        />
                        <Text style={styles.hint}>
                            A moment is a short window around a problem or the key moment. Full recording on a card
                            plays that whole recording.
                        </Text>
                    </Section>
                    <Section label="Speed">
                        {lock ? (
                            <View style={styles.lockRow} testID="feed-lock-row">
                                <LockIcon size={iconSizes.inline} color={colors.secondary} />
                                <Text
                                    style={styles.lockText}
                                >{`Locked at ${lock.rate}x. Long press and pull down to unlock.`}</Text>
                                <Pressable44
                                    onPress={onUnlock}
                                    accessibilityLabel="Unlock"
                                    style={styles.unlockButton}
                                    pressedBackground={colors.pressed}
                                    testID="feed-unlock"
                                >
                                    <Text style={styles.unlockText}>Unlock</Text>
                                </Pressable44>
                            </View>
                        ) : null}
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
                        <Text style={styles.hint}>{holdHint(settings.speed)}</Text>
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
                    <Section label="A whole recording starts at">
                        <SegmentedPill
                            height={40}
                            segments={(['key', 'beginning'] as const).map((startAt) => ({
                                key: startAt,
                                accessibilityLabel: startAt === 'key' ? 'Key moment' : 'Beginning',
                                accessibilityRole: 'radio',
                                selected: settings.startAt === startAt,
                                onPress: () => onChange({ startAt }),
                                children: (
                                    <Text style={styles.segmentText}>
                                        {startAt === 'key' ? 'Key moment' : 'Beginning'}
                                    </Text>
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
                    <Section label="Phone recordings">
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
                                    <Text style={styles.segmentText}>
                                        {phoneFit === 'fill' ? 'Fill' : 'Whole screen'}
                                    </Text>
                                ),
                            }))}
                        />
                    </Section>
                    <View style={styles.switchRow}>
                        <View style={styles.switchText}>
                            <Text style={styles.rowLabel}>Skip inactivity</Text>
                            <Text style={styles.hint}>Jumps over stretches where nothing happens.</Text>
                        </View>
                        <Switch
                            value={settings.skipInactivity}
                            onValueChange={(skipInactivity) => onChange({ skipInactivity })}
                            trackColor={{ true: colors.switchOn, false: colors.switchOff }}
                            thumbColor={colors.white}
                            accessibilityLabel="Skip inactivity"
                            testID="feed-skip-inactivity"
                        />
                    </View>
                    {showsExportCost ? (
                        <Text style={styles.footnote}>
                            Videos are prepared on the server when you stay on a session or press Play. Each one counts
                            toward your team's monthly video limit.
                        </Text>
                    ) : null}
                </ScrollView>
            </GestureDetector>
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
                <ScrollView style={{ maxHeight: height * 0.64 }} contentContainerStyle={styles.infoContent}>
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
                </ScrollView>
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
    footnote: {
        ...type.meta,
        color: colors.tertiary,
        marginTop: 18,
        marginBottom: 4,
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
    lockRow: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        marginBottom: 10,
    },
    lockText: {
        ...type.meta,
        flex: 1,
        color: colors.secondary,
    },
    unlockButton: {
        height: 34,
        paddingHorizontal: 14,
        borderRadius: 17,
        justifyContent: 'center',
        borderWidth: 1,
        borderColor: colors.border,
    },
    unlockText: {
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
