import { useFocusEffect } from 'expo-router'
import { type ReactElement, useCallback, useState } from 'react'
import { Linking, RefreshControl, ScrollView, type StyleProp, Text, type TextStyle, View } from 'react-native'

import type { ProjectScope } from '@/api/reports'
import { changeNavPin } from '@/features/tabs/navPinActions'
import { type NavChrome, useIsNavPinned } from '@/features/tabs/navPinStore'
import { TabHeaderPublisher } from '@/features/tabs/TabHeaderPublisher'
import { TABS_HEADER_BOTTOM } from '@/features/tabs/TabsHeader'
import { HeaderMenu } from '@/features/views/screen/HeaderMenu'
import { ViewChrome } from '@/features/views/screen/ViewChrome'
import { useViewBack, ViewScreenFrame } from '@/features/views/screen/ViewScreenFrame'
import { ViewSkeleton } from '@/features/views/screen/ViewSkeleton'
import { useViewsContext } from '@/features/views/useViewsContext'
import { ViewsReauthState } from '@/features/views/ViewsReauthState'
import { type Toasts, useToasts, ViewsToast } from '@/features/views/ViewsToast'
import { viewWebUrl } from '@/features/views/webLinks'
import { safeHttpsUrl } from '@/lib/urls'
import { useNow } from '@/lib/useNow'
import type { LiveBreakdownKind, LiveEventRow } from '@/model/live'
import type { ViewEntry } from '@/model/views'
import { Eyebrow } from '@/ui/Eyebrow'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { PauseIcon } from '@/ui/icons/PauseIcon'
import { PinIcon } from '@/ui/icons/PinIcon'
import { PlayIcon } from '@/ui/icons/PlayIcon'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { LiveDot } from '@/ui/LiveDot'
import { Pressable44 } from '@/ui/Pressable44'
import { StateView } from '@/ui/StateView'
import { SCREEN_CONTENT_TOP } from '@/ui/screenLayout'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, layout, radii, type } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets, useTabBottomOffset } from '@/ui/useScreenInsets'
import { type ScrollTitleState, useScrollTitle } from '@/ui/useScrollTitle'

import {
    trackLiveBreakdownChanged,
    trackLiveEventSheetOpened,
    trackLiveOpened,
    trackLiveOpenedInWeb,
} from './analytics'
import { useLiveFeed } from './hooks'
import { LiveActivityCard } from './LiveActivityCard'
import { LiveBreakdownCard } from './LiveBreakdownCard'
import { LiveEventSheet } from './LiveEventSheet'
import { LiveEventsCard } from './LiveEventsCard'
import { LiveRankedTable } from './LiveRankedTable'
import { LiveStats } from './LiveStats'
import type { LiveStatus } from './liveController'
import { statusText } from './liveFormat'

/** A pushed screen has no bottom bar, so the toast sits low. */
const TOAST_BOTTOM = 48

export function LiveScreen({ from, chrome }: { from: ViewEntry; chrome: NavChrome }): ReactElement {
    const styles = useStyles()
    const { access, scope, identity } = useViewsContext()
    const scrollTitle = useScrollTitle('Live')
    const back = useViewBack()
    const insets = useScreenInsets()
    const tabBottom = useTabBottomOffset()
    // The screen owns the toasts, so the More menu's pin change shows one whatever the body shows.
    const toasts = useToasts()
    const pinned = useIsNavPinned('live')
    const [menuOpen, setMenuOpen] = useState(false)
    const allowed = access.state === 'ok'
    const tab = chrome === 'tab'
    useFocusEffect(
        useCallback(() => {
            trackLiveOpened({ from, chrome })
        }, [from, chrome])
    )
    const webUrl = viewWebUrl(scope, '/web/live')
    let body: ReactElement
    if (allowed) {
        body = <LiveBody key={identity} chrome={chrome} scope={scope} scrollTitle={scrollTitle} toasts={toasts} />
    } else if (tab) {
        body = (
            <View
                style={[styles.fill, { paddingTop: topOffset(insets, TABS_HEADER_BOTTOM), paddingBottom: tabBottom }]}
            >
                <TabHeaderPublisher tab="live" status={null} />
                <ViewsReauthState access={access} />
            </View>
        )
    } else {
        body = <ViewsReauthState access={access} />
    }
    return (
        <ViewScreenFrame
            overlayHost={!tab}
            chrome={
                tab ? null : (
                    <ViewChrome
                        title={scrollTitle.title}
                        onBack={back}
                        onMore={allowed ? () => setMenuOpen(true) : undefined}
                    />
                )
            }
        >
            {body}
            {tab ? null : (
                <HeaderMenu
                    visible={menuOpen}
                    onClose={() => setMenuOpen(false)}
                    testID="live-menu"
                    items={[
                        {
                            key: pinned ? 'unpin' : 'pin',
                            label: pinned ? 'Unpin from navigation' : 'Pin to navigation',
                            Icon: PinIcon,
                            onPress: () => changeNavPin('live', !pinned, 'list_menu', toasts.show),
                        },
                        {
                            key: 'web',
                            label: 'Open on web',
                            Icon: ExternalLinkIcon,
                            disabled: !webUrl,
                            meta: webUrl ? null : 'Not in the demo',
                            onPress: () => {
                                const safe = webUrl ? safeHttpsUrl(webUrl) : undefined
                                if (safe) {
                                    trackLiveOpenedInWeb()
                                    Linking.openURL(safe).catch(() => undefined)
                                }
                            },
                        },
                    ]}
                />
            )}
            <ViewsToast toast={toasts.toast} onHide={toasts.hide} bottom={tab ? undefined : TOAST_BOTTOM} />
        </ViewScreenFrame>
    )
}

interface LiveBodyProps {
    chrome: NavChrome
    scope: ProjectScope | null
    scrollTitle: ScrollTitleState
    toasts: Toasts
}

function LiveBody({ chrome, scope, scrollTitle, toasts }: LiveBodyProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const insets = useScreenInsets()
    const tabBottom = useTabBottomOffset()
    const tab = chrome === 'tab'
    const feed = useLiveFeed((kind) => {
        if (kind === 'refresh_failed') {
            toasts.show("Couldn't update live data. Retrying…")
        }
    })
    const [breakdown, setBreakdown] = useState<LiveBreakdownKind>('devices')
    const [sheetOpen, setSheetOpen] = useState(false)
    const [sheetEvent, setSheetEvent] = useState<LiveEventRow | null>(null)
    const { snapshot } = feed
    const contentTop = topOffset(insets, tab ? TABS_HEADER_BOTTOM : SCREEN_CONTENT_TOP)
    const contentBottom = tab ? tabBottom : bottomOffset(insets, 48)

    const openEvent = useCallback((event: LiveEventRow) => {
        trackLiveEventSheetOpened({ kind: event.kind })
        setSheetEvent(event)
        setSheetOpen(true)
    }, [])
    const changeBreakdown = (kind: LiveBreakdownKind): void => {
        trackLiveBreakdownChanged({ breakdown: kind })
        setBreakdown(kind)
    }

    const title = (
        <LiveTitle
            tab={tab}
            status={feed.status}
            screenActive={feed.screenActive}
            updatedAt={feed.updatedAt}
            paused={feed.paused}
            onPause={feed.pause}
            onResume={feed.resume}
            onTitleLayout={scrollTitle.onTitleLayout}
        />
    )
    const nothingYet = Object.values(snapshot).every((part) => part === null)
    let content: ReactElement
    if (feed.loadFailed && !feed.reading) {
        content = (
            <StateView
                icon={<WarningIcon size={iconSizes.empty} color={colors.tertiary} />}
                title="Couldn't load live data"
                message="Check your connection and try again."
                actionLabel="Try again"
                onAction={feed.retry}
                testID="live-error"
            />
        )
    } else if (nothingYet) {
        content = (
            <View testID="live-loading">
                <ViewSkeleton cards={3} />
            </View>
        )
    } else {
        const activity = snapshot.activity
        content = (
            <View style={styles.cards}>
                <LiveStats
                    usersOnline={feed.usersOnline}
                    uniqueVisitors={activity?.uniqueVisitors ?? null}
                    pageviews={activity?.pageviews ?? null}
                    onAbout={(text) => toasts.show(text)}
                />
                <LiveActivityCard activity={activity} />
                <LiveRankedTable
                    title="Top pages (last 30 minutes)"
                    columnLabel="Path"
                    rows={snapshot.topPages}
                    emptyText="No pageviews recorded in the last 30 minutes"
                    mono
                    version={feed.updatedAt}
                    testID="live-top-pages"
                />
                <LiveRankedTable
                    title="Top referrers (last 30 minutes)"
                    columnLabel="Referrer"
                    rows={snapshot.topReferrers}
                    emptyText="No referrer data in the last 30 minutes"
                    mono
                    version={feed.updatedAt}
                    testID="live-top-referrers"
                />
                <LiveBreakdownCard kind={breakdown} breakdown={snapshot[breakdown]} onChange={changeBreakdown} />
                <LiveEventsCard events={snapshot.events} onOpen={openEvent} screenActive={feed.screenActive} />
            </View>
        )
    }

    return (
        <View style={styles.fill}>
            {/* The status line sits in the content's first row, so the shared header shows the title alone. */}
            {tab ? <TabHeaderPublisher tab="live" status={null} /> : null}
            <ScrollView
                contentContainerStyle={[styles.content, { paddingTop: contentTop, paddingBottom: contentBottom }]}
                onScroll={scrollTitle.onScroll}
                scrollEventThrottle={16}
                refreshControl={
                    <RefreshControl
                        refreshing={feed.pulling}
                        onRefresh={feed.pull}
                        tintColor={colors.tertiary}
                        progressBackgroundColor={colors.surface}
                        colors={[colors.tertiary]}
                        progressViewOffset={contentTop}
                    />
                }
                testID="live-scroll"
            >
                {title}
                {feed.paused ? <PausedBanner onResume={feed.resume} /> : null}
                {content}
            </ScrollView>
            <LiveEventSheet
                visible={sheetOpen}
                screenActive={feed.screenActive}
                event={sheetEvent}
                scope={scope}
                onClose={() => setSheetOpen(false)}
                onNotice={toasts.show}
            />
        </View>
    )
}

interface LiveTitleProps {
    /** On a tab the shared tabs header draws the title, so one row holds the dot, the status line and Pause. */
    tab: boolean
    status: LiveStatus
    screenActive: boolean
    updatedAt: number | null
    paused: boolean
    onPause: () => void
    onResume: () => void
    onTitleLayout: ScrollTitleState['onTitleLayout']
}

function LiveTitle({
    tab,
    status,
    screenActive,
    updatedAt,
    paused,
    onPause,
    onResume,
    onTitleLayout,
}: LiveTitleProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const pauseButton = (
        <Pressable44
            onPress={paused ? onResume : onPause}
            accessibilityLabel={paused ? 'Resume live updates' : 'Pause live updates'}
            pressedBackground={colors.pressed}
            style={styles.pauseButton}
            testID="live-pause"
        >
            {paused ? <PlayIcon size={12} color={colors.ink} /> : <PauseIcon size={16} color={colors.ink} />}
            <Text style={styles.pauseText}>{paused ? 'Resume' : 'Pause'}</Text>
        </Pressable44>
    )
    if (tab) {
        return (
            <View style={[styles.titleBlock, styles.titleRow, styles.tabTitleRow]}>
                <View style={styles.tabStatus}>
                    <LiveDot on={status === 'live'} animate={screenActive} />
                    <LiveStatusLine
                        status={status}
                        screenActive={screenActive}
                        updatedAt={updatedAt}
                        numberOfLines={1}
                        style={styles.tabStatusText}
                    />
                </View>
                {pauseButton}
            </View>
        )
    }
    return (
        <View style={styles.titleBlock}>
            <View onLayout={onTitleLayout}>
                <Eyebrow>Web analytics</Eyebrow>
                <View style={styles.titleRow}>
                    <View style={styles.titleText}>
                        <Text style={styles.title} accessibilityRole="header">
                            Live
                        </Text>
                        <LiveDot on={status === 'live'} animate={screenActive} />
                    </View>
                    {pauseButton}
                </View>
            </View>
            <LiveStatusLine status={status} screenActive={screenActive} updatedAt={updatedAt} />
        </View>
    )
}

interface LiveStatusLineProps {
    status: LiveStatus
    screenActive: boolean
    updatedAt: number | null
    /** The tab's row truncates the line beside the Pause pill. */
    numberOfLines?: number
    style?: StyleProp<TextStyle>
}

/** Its own component, so the one-second clock re-renders only this line. */
function LiveStatusLine({ status, screenActive, updatedAt, numberOfLines, style }: LiveStatusLineProps): ReactElement {
    const styles = useStyles()
    const now = useNow(screenActive && status === 'live' ? 1000 : null).getTime()
    return (
        <Text
            style={[styles.status, style]}
            numberOfLines={numberOfLines}
            accessibilityLiveRegion="polite"
            testID="live-status"
        >
            {statusText(status, updatedAt, now)}
        </Text>
    )
}

function PausedBanner({ onResume }: { onResume: () => void }): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <View style={styles.banner} testID="live-paused-banner">
            <Text style={styles.bannerText}>Paused. Tap Resume to catch up.</Text>
            <Pressable44
                onPress={onResume}
                accessibilityLabel="Resume live updates"
                pressedBackground={colors.pressed}
                style={styles.pauseButton}
                testID="live-banner-resume"
            >
                <PlayIcon size={12} color={colors.ink} />
                <Text style={styles.pauseText}>Resume</Text>
            </Pressable44>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    fill: {
        flex: 1,
    },
    content: {
        paddingHorizontal: layout.inboxGutter,
    },
    cards: {
        gap: 12,
    },
    titleBlock: {
        paddingHorizontal: 6,
        marginBottom: 16,
    },
    titleRow: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
        marginTop: 4,
    },
    tabTitleRow: {
        marginTop: 0,
    },
    tabStatus: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
        flexShrink: 1,
    },
    tabStatusText: {
        flexShrink: 1,
    },
    titleText: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
    },
    title: {
        ...type.screenTitle,
        fontSize: 26,
        lineHeight: 34,
        color: colors.ink,
    },
    status: {
        ...type.meta,
        lineHeight: 18,
        minHeight: 18,
        color: colors.tertiary,
        fontVariant: ['tabular-nums'],
    },
    pauseButton: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        height: 40,
        paddingHorizontal: 16,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
    },
    pauseText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
    banner: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        marginBottom: 12,
        paddingVertical: 10,
        paddingLeft: 14,
        paddingRight: 10,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
    },
    bannerText: {
        ...type.bodySmall,
        flex: 1,
        color: colors.ink,
    },
}))
