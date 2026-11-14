import { useFocusEffect } from 'expo-router'
import { type ReactElement, useCallback, useEffect, useRef, useState } from 'react'
import { Linking, RefreshControl, ScrollView, type ScrollViewInstance, Text, View } from 'react-native'

import type { ProjectScope } from '@/api/reports'
import type { NavChrome } from '@/features/tabs/navPinStore'
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
import { liveBreakdownKinds } from '@/model/adapters/live'
import type { LiveBreakdownKind, LiveEventRow, LiveProjectState } from '@/model/live'
import type { ViewEntry } from '@/model/views'
import { Eyebrow } from '@/ui/Eyebrow'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { LiveDot } from '@/ui/LiveDot'
import { StateView } from '@/ui/StateView'
import { SCREEN_CONTENT_TOP } from '@/ui/screenLayout'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, layout, type } from '@/ui/tokens'
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
import { LiveAudienceControl } from './LiveAudienceControl'
import { LiveBreakdownCard } from './LiveBreakdownCard'
import { LiveEventSheet } from './LiveEventSheet'
import { LiveEventsCard } from './LiveEventsCard'
import { LiveMapCard } from './LiveMapCard'
import { LiveMobileMetrics } from './LiveMobileMetrics'
import { LiveNoTraffic } from './LiveNoTraffic'
import { LiveRankedTable } from './LiveRankedTable'
import { LiveStats } from './LiveStats'
import type { LiveStatus } from './liveController'
import { statusText } from './liveFormat'
import { useLivePreference } from './livePreference'
import { useLiveAudienceNativeMenu } from './useLiveAudienceNativeMenu'

/** A pushed screen has no bottom bar, so the toast sits low. */
const TOAST_BOTTOM = 48
const LIVE_TAB_CONTENT_TOP = TABS_HEADER_BOTTOM + 4

export function LiveScreen({ from, chrome }: { from: ViewEntry; chrome: NavChrome }): ReactElement {
    const styles = useStyles()
    const { access, scope, identity } = useViewsContext()
    const scrollTitle = useScrollTitle('Live')
    const back = useViewBack()
    const insets = useScreenInsets()
    const tabBottom = useTabBottomOffset()
    const toasts = useToasts()
    const [menuOpen, setMenuOpen] = useState(false)
    const allowed = access.state === 'ok'
    const nativeAudienceMenu = useLiveAudienceNativeMenu(allowed && chrome === 'stack')
    const tab = chrome === 'tab'
    // The tabs layout counts Home opens once per tab switch, because this focus effect also fires when a pushed screen,
    // Settings or the chat sheet closes over Home.
    useFocusEffect(
        useCallback(() => {
            if (chrome === 'stack') {
                trackLiveOpened({ from, chrome })
            }
        }, [from, chrome])
    )
    const webUrl = viewWebUrl(scope, '/web/live')
    let body: ReactElement
    if (allowed) {
        body = <LiveBody key={identity} chrome={chrome} scope={scope} scrollTitle={scrollTitle} toasts={toasts} />
    } else if (tab) {
        body = (
            <View
                style={[styles.fill, { paddingTop: topOffset(insets, LIVE_TAB_CONTENT_TOP), paddingBottom: tabBottom }]}
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
                        accessory={allowed ? <LiveAudienceControl /> : null}
                        nativeAccessory={nativeAudienceMenu}
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
    const scroll = useRef<ScrollViewInstance>(null)
    const { preference } = useLivePreference()
    const previousPreference = useRef(preference)
    useEffect(() => {
        if (preference !== previousPreference.current) {
            previousPreference.current = preference
            scroll.current?.scrollTo({ y: 0, animated: false })
        }
    }, [preference])
    const feed = useLiveFeed((kind) => {
        if (kind === 'refresh_failed') {
            toasts.show("Couldn't update live data. Retrying…")
        }
    })
    const [breakdown, setBreakdown] = useState<LiveBreakdownKind>('devices')
    const [sheetOpen, setSheetOpen] = useState(false)
    const [sheetEvent, setSheetEvent] = useState<LiveEventRow | null>(null)
    const { snapshot, state } = feed
    const detectedAudience = snapshot.profile?.kind ?? (state === 'app_only' ? 'mobile' : 'unknown')
    const audience =
        snapshot.profile && snapshot.profile.kind !== 'unknown'
            ? snapshot.profile.kind
            : state === 'app_only'
              ? 'mobile'
              : 'web'
    const mobile = audience === 'mobile'
    const mixed = audience === 'mixed'
    const hasMobile = mobile || mixed
    const contentTop = topOffset(insets, tab ? LIVE_TAB_CONTENT_TOP : SCREEN_CONTENT_TOP)
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

    const nothingYet = [
        snapshot.activity,
        snapshot.topPages,
        snapshot.topScreens,
        snapshot.topReferrers,
        snapshot.devices,
        snapshot.browsers,
        snapshot.platforms,
        snapshot.countries,
        snapshot.world,
        snapshot.events,
        snapshot.usersOnline,
        snapshot.mobileMetrics,
    ].every((part) => part == null)
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
    } else if (state === 'quiet' || state === 'not_set_up') {
        content = <LiveNoTraffic state={state} scope={scope} mobile={mobile} />
    } else if (nothingYet) {
        content = (
            <View testID="live-loading">
                <ViewSkeleton cards={3} />
            </View>
        )
    } else {
        const activity = snapshot.activity
        // A failed top-list query retains rows that may differ from the current project's activity.
        const appOnly = mobile || state === 'app_only'
        const screens = mobile || snapshot.topPagesMode === 'screens'
        const kinds: LiveBreakdownKind[] = mobile
            ? ['platforms', 'countries']
            : mixed
              ? ['platforms', ...liveBreakdownKinds(snapshot)]
              : liveBreakdownKinds(snapshot)
        const shownBreakdown = kinds.includes(breakdown) ? breakdown : kinds[0]
        content = (
            <View style={styles.cards}>
                <LiveStats
                    usersOnline={feed.usersOnline}
                    uniqueVisitors={activity?.uniqueVisitors ?? null}
                    pageviews={activity?.pageviews ?? null}
                    onAbout={(text) => toasts.show(text)}
                    audience={hasMobile ? (mixed ? 'mixed' : 'mobile') : 'web'}
                    metrics={
                        mobile
                            ? [
                                  {
                                      key: 'users-online',
                                      label: 'Users online',
                                      value: feed.usersOnline,
                                      about: 'People active in your mobile app right now.',
                                  },
                                  {
                                      key: 'active-users',
                                      label: 'Active users',
                                      value: activity?.uniqueVisitors ?? null,
                                      about: 'Distinct users in the last 30 minutes.',
                                  },
                                  {
                                      key: 'screenviews',
                                      label: 'Screen views',
                                      value: activity?.screenviews ?? null,
                                      about: 'Total mobile screens viewed in the last 30 minutes.',
                                  },
                              ]
                            : undefined
                    }
                />
                {hasMobile ? <LiveMobileMetrics metrics={snapshot.mobileMetrics} onAbout={toasts.show} /> : null}
                {snapshot.world?.countries.length === 0 ? null : (
                    <LiveMapCard
                        world={snapshot.world}
                        paused={feed.paused}
                        users={hasMobile}
                        mobileOnly={mobile}
                        webOnly={detectedAudience === 'web'}
                    />
                )}
                <LiveActivityCard activity={activity} audience={hasMobile ? (mixed ? 'mixed' : 'mobile') : 'web'} />
                {/* Keyed by form, so a switch between pages and screens redraws the rows instead of sliding them. */}
                {screens ? (
                    <LiveRankedTable
                        key="screens"
                        title="Top screens (last 30 minutes)"
                        columnLabel="Screen"
                        rows={snapshot.topScreens ?? snapshot.topPages}
                        emptyText="No screen views recorded in the last 30 minutes"
                        version={feed.updatedAt}
                        testID="live-top-screens"
                    />
                ) : (
                    <LiveRankedTable
                        key="pages"
                        title="Top pages (last 30 minutes)"
                        columnLabel="Path"
                        rows={snapshot.topPages}
                        emptyText="No pageviews recorded in the last 30 minutes"
                        mono
                        version={feed.updatedAt}
                        testID="live-top-pages"
                    />
                )}
                {mixed && !screens ? (
                    <LiveRankedTable
                        title="Top screens (last 30 minutes)"
                        columnLabel="Screen"
                        rows={snapshot.topScreens ?? null}
                        emptyText="No screen views recorded in the last 30 minutes"
                        version={feed.updatedAt}
                        testID="live-top-screens"
                    />
                ) : null}
                {appOnly ? null : (
                    <LiveRankedTable
                        title="Top referrers (last 30 minutes)"
                        columnLabel="Referrer"
                        rows={snapshot.topReferrers}
                        emptyText="No referrer data in the last 30 minutes"
                        mono
                        version={feed.updatedAt}
                        testID="live-top-referrers"
                    />
                )}
                {shownBreakdown ? (
                    <LiveBreakdownCard
                        kinds={kinds}
                        kind={shownBreakdown}
                        breakdown={snapshot[shownBreakdown] ?? null}
                        onChange={changeBreakdown}
                    />
                ) : null}
                <LiveEventsCard
                    events={snapshot.events}
                    onOpen={openEvent}
                    screenActive={feed.screenActive}
                    audience={hasMobile ? (mixed ? 'mixed' : 'mobile') : 'web'}
                />
            </View>
        )
    }

    return (
        <View style={styles.fill}>
            {tab ? (
                <TabHeaderPublisher
                    tab="live"
                    status={feed.status === 'reconnecting' ? 'Reconnecting…' : null}
                    liveAudience
                />
            ) : null}
            <ScrollView
                ref={scroll}
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
                {/* On a tab the shared tabs header draws the title. */}
                {tab ? null : (
                    <LiveTitle
                        status={feed.status}
                        state={state}
                        screenActive={feed.screenActive}
                        updatedAt={feed.updatedAt}
                        onTitleLayout={scrollTitle.onTitleLayout}
                        audience={detectedAudience}
                    />
                )}
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
    audience: 'web' | 'mobile' | 'mixed' | 'unknown'
    status: LiveStatus
    state: LiveProjectState | null
    screenActive: boolean
    updatedAt: number | null
    onTitleLayout: ScrollTitleState['onTitleLayout']
}

/** The pushed screen's title block. */
function LiveTitle({ audience, status, state, screenActive, updatedAt, onTitleLayout }: LiveTitleProps): ReactElement {
    const styles = useStyles()
    const on = status === 'live' && state !== 'quiet' && state !== 'not_set_up'
    return (
        <View style={styles.titleBlock}>
            <View onLayout={onTitleLayout}>
                <Eyebrow>
                    {audience === 'mobile'
                        ? 'Mobile analytics'
                        : audience === 'mixed'
                          ? 'Web + mobile analytics'
                          : audience === 'unknown'
                            ? 'Activity analytics'
                            : 'Web analytics'}
                </Eyebrow>
                <View style={styles.titleRow}>
                    <View style={styles.titleText}>
                        <Text style={styles.title} accessibilityRole="header">
                            Live
                        </Text>
                        <LiveDot on={on} animate={screenActive} />
                    </View>
                </View>
            </View>
            <LiveStatusLine status={status} state={state} screenActive={screenActive} updatedAt={updatedAt} />
        </View>
    )
}

interface LiveStatusLineProps {
    status: LiveStatus
    state: LiveProjectState | null
    screenActive: boolean
    updatedAt: number | null
}

/** Its own component, so the one-second clock re-renders only this line. */
function LiveStatusLine({ status, state, screenActive, updatedAt }: LiveStatusLineProps): ReactElement {
    const styles = useStyles()
    const ticking = screenActive && status === 'live' && state !== 'quiet' && state !== 'not_set_up'
    const now = useNow(ticking ? 1000 : null).getTime()
    return (
        <Text style={styles.status} accessibilityLiveRegion="polite" testID="live-status">
            {statusText(status, updatedAt, now, state)}
        </Text>
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
}))
