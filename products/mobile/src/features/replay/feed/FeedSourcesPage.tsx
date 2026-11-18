import type { ComponentType, ReactElement } from 'react'
import { FlatList, Image, Modal, ScrollView, Text, View } from 'react-native'

import { ChevronLeftIcon } from '@/ui/icons/ChevronLeftIcon'
import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { ErrorTriangleIcon } from '@/ui/icons/ErrorTriangleIcon'
import { FlagIcon } from '@/ui/icons/FlagIcon'
import { RecordingIcon } from '@/ui/icons/RecordingIcon'
import { SparklesIcon } from '@/ui/icons/SparklesIcon'
import type { IconProps } from '@/ui/icons/types'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'
import { useScreenInsets } from '@/ui/useScreenInsets'

import { useFrameUrl } from '../hooks'
import { itemTitle } from './FeedCard'
import { SOURCE_LABELS } from './FeedSheets'
import { compactDuration } from './feedAdapters'
import { FEED_SOURCES, type FeedItem, type FeedSource } from './feedModel'
import { useFeed } from './useFeed'

const SHELF_ICONS: Record<FeedSource, ComponentType<IconProps>> = {
    highlights: SparklesIcon,
    rage: FlagIcon,
    errors: ErrorTriangleIcon,
    newest: RecordingIcon,
}

const SHELF_EMPTY: Record<FeedSource, string> = {
    highlights: 'Highlights need Replay Vision. It ranks recordings and finds their key moments.',
    rage: 'No recordings with rage clicks in the last 7 days.',
    errors: 'No recordings with errors in the last 7 days.',
    newest: 'No finished recordings in the last 7 days.',
}

interface FeedSourcesPageProps {
    visible: boolean
    playing: FeedSource
    onPlay: (source: FeedSource, sessionId: string | null) => void
    onClose: () => void
}

/** Where the feed's source is chosen: one shelf per source, each from the query the feed plays. */
export function FeedSourcesPage({ visible, playing, onPlay, onClose }: FeedSourcesPageProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const insets = useScreenInsets()
    return (
        <Modal visible={visible} animationType="slide" presentationStyle="fullScreen" onRequestClose={onClose}>
            <View style={[styles.page, { paddingTop: insets.top + 4 }]} testID="feed-sources">
                <View style={styles.header}>
                    <Pressable44
                        onPress={onClose}
                        accessibilityLabel="Back to the feed"
                        style={styles.back}
                        pressedBackground={colors.pressed}
                        testID="feed-sources-back"
                    >
                        <ChevronLeftIcon size={20} color={colors.ink} />
                        <Text style={styles.backText}>Back</Text>
                    </Pressable44>
                </View>
                <ScrollView contentContainerStyle={{ paddingBottom: insets.bottom + 24 }}>
                    <Text style={styles.title}>Sessions</Text>
                    <Text style={styles.lead}>Choose what the feed plays</Text>
                    {visible
                        ? FEED_SOURCES.map((source) => (
                              <Shelf
                                  key={source}
                                  source={source}
                                  playing={source === playing}
                                  onPlay={(sessionId) => onPlay(source, sessionId)}
                              />
                          ))
                        : null}
                </ScrollView>
            </View>
        </Modal>
    )
}

interface ShelfProps {
    source: FeedSource
    playing: boolean
    onPlay: (sessionId: string | null) => void
}

function Shelf({ source, playing, onPlay }: ShelfProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const feed = useFeed(source)
    const Icon = SHELF_ICONS[source]
    const items = feed.items ?? []
    return (
        <View style={styles.shelf} testID={`feed-shelf-${source}`}>
            <Pressable44
                onPress={() => onPlay(null)}
                accessibilityLabel={`Play ${SOURCE_LABELS[source]}`}
                style={styles.shelfHeader}
                pressedBackground={colors.pressed}
                hitSlop={0}
            >
                <Icon size={17} color={colors.ink} />
                <Text style={styles.shelfTitle}>{SOURCE_LABELS[source]}</Text>
                {playing ? (
                    <View style={styles.playingChip}>
                        <Text style={styles.playingText}>Playing</Text>
                    </View>
                ) : null}
                <View style={styles.spacer} />
                {items.length > 0 ? <Text style={styles.count}>{String(items.length)}</Text> : null}
                <ChevronRightIcon size={15} color={colors.secondary} />
            </Pressable44>
            {feed.items === undefined && !feed.error ? (
                <View style={styles.tilesLoading}>
                    {[0, 1, 2].map((slot) => (
                        <View key={slot} style={[styles.tile, styles.tileSkeleton]} />
                    ))}
                </View>
            ) : items.length === 0 ? (
                <Text style={styles.empty}>
                    {feed.error ? "Couldn't load this source. Pull the feed down to try again." : SHELF_EMPTY[source]}
                </Text>
            ) : (
                <FlatList
                    horizontal
                    data={items}
                    keyExtractor={(item) => item.recording.sessionId}
                    renderItem={({ item }) => <Tile item={item} onPress={() => onPlay(item.recording.sessionId)} />}
                    showsHorizontalScrollIndicator={false}
                    contentContainerStyle={styles.tiles}
                />
            )}
        </View>
    )
}

function Tile({ item, onPress }: { item: FeedItem; onPress: () => void }): ReactElement {
    const styles = useStyles()
    const summary = item.summary
    const chapter = summary?.chapters.find((entry) => entry.hasFrame)?.index ?? null
    const frame = useFrameUrl(summary && chapter !== null ? summary.observationId : null, chapter)
    return (
        <Pressable44
            onPress={onPress}
            accessibilityLabel={`${itemTitle(item)}, ${compactDuration(item.recording.durationSeconds)}`}
            style={styles.tile}
            hitSlop={0}
        >
            {frame.data ? (
                <Image source={{ uri: frame.data }} style={styles.tileImage} accessibilityIgnoresInvertColors />
            ) : (
                <View style={styles.tilePlaceholder}>
                    <Text style={styles.tilePath} numberOfLines={2}>
                        {item.recording.startPath ?? item.recording.personLabel}
                    </Text>
                </View>
            )}
            <View style={styles.tileShade} />
            <Text style={styles.tileTitle} numberOfLines={3}>
                {itemTitle(item)}
            </Text>
            <View style={styles.tileBadge}>
                <Text style={styles.tileBadgeText}>{compactDuration(item.recording.durationSeconds)}</Text>
            </View>
        </Pressable44>
    )
}

const useStyles = createStyles(({ colors }) => ({
    page: {
        flex: 1,
        backgroundColor: colors.background,
    },
    header: {
        height: 48,
        paddingHorizontal: 12,
        flexDirection: 'row',
        alignItems: 'center',
    },
    back: {
        height: 40,
        paddingLeft: 8,
        paddingRight: 14,
        borderRadius: radii.pill,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 2,
        backgroundColor: colors.surface,
        borderWidth: 1,
        borderColor: colors.border,
    },
    backText: {
        ...type.bodySmallStrong,
        color: colors.ink,
    },
    title: {
        ...type.screenTitle,
        color: colors.ink,
        marginTop: 8,
        marginHorizontal: 20,
    },
    lead: {
        ...type.meta,
        color: colors.secondary,
        marginTop: 2,
        marginHorizontal: 20,
        marginBottom: 8,
    },
    shelf: {
        marginTop: 14,
    },
    shelfHeader: {
        height: 40,
        marginHorizontal: 12,
        paddingHorizontal: 8,
        borderRadius: radii.option,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
    },
    shelfTitle: {
        ...type.sectionHeader,
        color: colors.ink,
    },
    playingChip: {
        height: 22,
        paddingHorizontal: 8,
        borderRadius: 11,
        justifyContent: 'center',
        backgroundColor: colors.pressed,
    },
    playingText: {
        ...type.meta,
        fontWeight: '600',
        color: colors.ink,
    },
    spacer: {
        flex: 1,
    },
    count: {
        ...type.meta,
        color: colors.secondary,
    },
    tiles: {
        gap: 10,
        paddingHorizontal: 20,
        paddingTop: 4,
    },
    tilesLoading: {
        flexDirection: 'row',
        gap: 10,
        paddingHorizontal: 20,
        paddingTop: 4,
    },
    tile: {
        width: 116,
        height: 184,
        borderRadius: radii.tile,
        overflow: 'hidden',
        backgroundColor: '#15161A',
    },
    tileSkeleton: {
        backgroundColor: colors.pressed,
    },
    tileImage: {
        position: 'absolute',
        top: 0,
        right: 0,
        bottom: 0,
        left: 0,
    },
    tilePlaceholder: {
        position: 'absolute',
        top: 0,
        right: 0,
        bottom: 0,
        left: 0,
        padding: 10,
        justifyContent: 'flex-start',
    },
    tilePath: {
        fontSize: 11,
        color: 'rgba(255,255,255,0.55)',
    },
    tileShade: {
        position: 'absolute',
        left: 0,
        right: 0,
        bottom: 0,
        height: 110,
        backgroundColor: 'rgba(0,0,0,0.45)',
    },
    tileTitle: {
        position: 'absolute',
        left: 9,
        right: 9,
        bottom: 34,
        fontSize: 13,
        fontWeight: '700',
        lineHeight: 16,
        color: '#FFFFFF',
    },
    tileBadge: {
        position: 'absolute',
        left: 9,
        bottom: 9,
        height: 20,
        paddingHorizontal: 7,
        borderRadius: 10,
        justifyContent: 'center',
        backgroundColor: 'rgba(0,0,0,0.6)',
    },
    tileBadgeText: {
        fontSize: 11,
        fontWeight: '700',
        color: '#FFFFFF',
    },
    empty: {
        ...type.meta,
        color: colors.secondary,
        marginHorizontal: 20,
        marginTop: 4,
    },
}))
