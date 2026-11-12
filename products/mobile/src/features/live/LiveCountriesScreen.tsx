import { type ReactElement, useCallback, useMemo, useRef, useState } from 'react'
import { type LayoutChangeEvent, Text, View } from 'react-native'
import Animated, {
    scrollTo,
    useAnimatedRef,
    useAnimatedScrollHandler,
    useAnimatedStyle,
    useSharedValue,
} from 'react-native-reanimated'
import { scheduleOnUI } from 'react-native-worklets'

import { useViewBack, ViewScreenFrame } from '@/features/views/screen/ViewScreenFrame'
import { ViewSkeleton } from '@/features/views/screen/ViewSkeleton'
import { useViewsContext } from '@/features/views/useViewsContext'
import { ViewsReauthState } from '@/features/views/ViewsReauthState'
import { plural } from '@/model/adapters/text'
import type { LiveBreakdownRow, LiveWorld } from '@/model/live'
import { Eyebrow } from '@/ui/Eyebrow'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { LiveDot } from '@/ui/LiveDot'
import { Pressable44 } from '@/ui/Pressable44'
import { ScreenChrome } from '@/ui/ScreenChrome'
import { StateView } from '@/ui/StateView'
import { SCREEN_CHROME_BOTTOM, SCREEN_CONTENT_TOP, screenLayout } from '@/ui/screenLayout'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, layout, type } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets } from '@/ui/useScreenInsets'
import { type ScrollTitleState, useScrollTitle } from '@/ui/useScrollTitle'

import { type LiveCountrySource, trackLiveCountryCleared, trackLiveCountrySelected } from './analytics'
import { useLiveWorld } from './hooks'
import { LiveCardNote } from './LiveCard'
import { LiveCountryList } from './LiveCountryList'
import { LIVE_ROW_HEIGHT } from './LiveSlidingRow'
import type { LiveStatus } from './liveController'
import { countriesStatusText, countryText } from './liveFormat'
import { WorldMap } from './map/WorldMap'
import { rowScrollTarget } from './rowScroll'

const TITLE = 'Visitors by country'

/** Live's countries on a large map and as a list. A tap on the map or on a row selects the country in both. */
export function LiveCountriesScreen({ country }: { country: string | null }): ReactElement {
    const { access } = useViewsContext()
    const scrollTitle = useScrollTitle(TITLE)
    const back = useViewBack()
    return (
        <ViewScreenFrame
            // Back only: the screen has no actions of its own, so it leaves out View chrome's More button.
            chrome={<ScreenChrome onBack={back} backTestID="view-back" title={scrollTitle.title} />}
        >
            {access.state === 'ok' ? (
                <CountriesBody initial={country} scrollTitle={scrollTitle} />
            ) : (
                <ViewsReauthState access={access} />
            )}
        </ViewScreenFrame>
    )
}

interface Layouts {
    viewport: number
    content: number
    mapBlock: { y: number; height: number } | null
    list: number | null
    rows: number | null
}

function CountriesBody({
    initial,
    scrollTitle,
}: {
    initial: string | null
    scrollTitle: ScrollTitleState
}): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const insets = useScreenInsets()
    const feed = useLiveWorld()
    const { world } = feed
    const [selected, setSelected] = useState<string | null>(initial)
    const counts = useMemo(
        () => Object.fromEntries((world?.countries ?? []).map((entry) => [entry.key, entry.count])),
        [world]
    )
    const selectedRow = world?.countries.find((entry) => entry.key === selected) ?? null

    const contentTop = topOffset(insets, SCREEN_CONTENT_TOP)
    // The map block's top padding fills the chrome's bottom padding, so no row shows between the chrome and the map.
    const stickTop = topOffset(insets, SCREEN_CHROME_BOTTOM) - screenLayout.bottomPadding
    const scrollRef = useAnimatedRef<Animated.ScrollView>()
    const scrollY = scrollTitle.title.scrollY
    // The map block sticks under the chrome once the scroll passes this offset, so a selected row and its outline
    // stay on screen together.
    const stickAt = useSharedValue(Number.POSITIVE_INFINITY)
    const onScroll = useAnimatedScrollHandler((event) => {
        scrollY.value = event.contentOffset.y
    })
    const sticky = useAnimatedStyle(() => ({
        transform: [{ translateY: Math.max(0, scrollY.value - stickAt.value) }],
    }))

    const layouts = useRef<Layouts>({ viewport: 0, content: 0, mapBlock: null, list: null, rows: null })
    const pendingScroll = useRef<string | null>(initial)
    const scrollToRow = useCallback(
        (code: string) => {
            const index = world?.countries.findIndex((entry) => entry.key === code) ?? -1
            const { viewport, content, mapBlock, list, rows } = layouts.current
            if (index < 0 || viewport === 0 || !mapBlock || list === null || rows === null) {
                pendingScroll.current = code
                return
            }
            pendingScroll.current = null
            const y = rowScrollTarget({
                rowTop: list + rows + index * LIVE_ROW_HEIGHT,
                rowHeight: LIVE_ROW_HEIGHT,
                blockTop: mapBlock.y,
                blockHeight: mapBlock.height,
                stickTop,
                scrollY: scrollY.value,
                viewportHeight: viewport,
                contentHeight: content,
            })
            if (y === null) {
                return
            }
            scheduleOnUI(() => {
                'worklet'
                scrollTo(scrollRef, 0, y, true)
            })
        },
        [world, scrollY, stickTop, scrollRef]
    )
    const retryPendingScroll = (): void => {
        if (pendingScroll.current) {
            scrollToRow(pendingScroll.current)
        }
    }

    const select = useCallback(
        (code: string, source: LiveCountrySource) => {
            trackLiveCountrySelected({ source })
            setSelected(code)
            if (source === 'map') {
                scrollToRow(code)
            }
        },
        [scrollToRow]
    )
    // Stable across renders, so the memoized map repaints only when the counts or the selection change.
    const onMapSelect = useCallback(
        (code: string | null) => {
            if (code) {
                select(code, 'map')
            }
        },
        [select]
    )
    const clear = (): void => {
        trackLiveCountryCleared()
        setSelected(null)
    }

    const onMapBlockLayout = (event: LayoutChangeEvent): void => {
        const { y, height } = event.nativeEvent.layout
        layouts.current.mapBlock = { y, height }
        stickAt.value = y - stickTop
        retryPendingScroll()
    }

    let content: ReactElement
    if (feed.loadFailed && !feed.reading) {
        content = (
            <StateView
                icon={<WarningIcon size={iconSizes.empty} color={colors.tertiary} />}
                title="Couldn't load live data"
                message="Check your connection and try again."
                actionLabel="Try again"
                onAction={feed.retry}
                testID="live-countries-error"
            />
        )
    } else if (!world) {
        content = (
            <View testID="live-countries-loading">
                <ViewSkeleton cards={2} />
            </View>
        )
    } else if (world.countries.length === 0) {
        content = <LiveCardNote text="No country data in the last 30 minutes" testID="live-countries-empty" />
    } else {
        content = (
            <>
                <Animated.View style={[styles.mapBlock, sticky]} onLayout={onMapBlockLayout}>
                    <WorldMap
                        counts={counts}
                        selected={selectedRow ? selected : null}
                        onSelect={onMapSelect}
                        testID="live-countries-map"
                    />
                    <MapCaption world={world} selected={selectedRow} onClear={clear} />
                </Animated.View>
                <View
                    onLayout={(event) => {
                        layouts.current.list = event.nativeEvent.layout.y
                        retryPendingScroll()
                    }}
                >
                    <LiveCountryList
                        countries={world.countries}
                        selected={selectedRow ? selected : null}
                        onSelect={(code) => select(code, 'row')}
                        onRowsLayout={(y) => {
                            layouts.current.rows = y
                            retryPendingScroll()
                        }}
                    />
                </View>
            </>
        )
    }

    return (
        <Animated.ScrollView
            ref={scrollRef}
            contentContainerStyle={[
                styles.content,
                { paddingTop: contentTop, paddingBottom: bottomOffset(insets, 48) },
            ]}
            onScroll={onScroll}
            scrollEventThrottle={16}
            onLayout={(event) => {
                layouts.current.viewport = event.nativeEvent.layout.height
            }}
            onContentSizeChange={(_width, height) => {
                layouts.current.content = height
                retryPendingScroll()
            }}
            testID="live-countries-scroll"
        >
            <CountriesTitle
                world={world}
                status={feed.status}
                screenActive={feed.screenActive}
                onTitleLayout={scrollTitle.onTitleLayout}
            />
            {content}
        </Animated.ScrollView>
    )
}

interface CountriesTitleProps {
    world: LiveWorld | null
    status: LiveStatus
    screenActive: boolean
    onTitleLayout: ScrollTitleState['onTitleLayout']
}

function CountriesTitle({ world, status, screenActive, onTitleLayout }: CountriesTitleProps): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.titleBlock}>
            <View onLayout={onTitleLayout}>
                <Eyebrow>Live</Eyebrow>
                <Text style={styles.title} accessibilityRole="header">
                    {TITLE}
                </Text>
            </View>
            <View style={styles.statusRow}>
                <LiveDot on={status === 'live'} animate={screenActive} />
                <Text style={styles.status} accessibilityLiveRegion="polite" testID="live-countries-status">
                    {countriesStatusText(status, world)}
                </Text>
            </View>
        </View>
    )
}

interface MapCaptionProps {
    world: LiveWorld
    selected: LiveBreakdownRow | null
    onClear: () => void
}

function MapCaption({ world, selected, onClear }: MapCaptionProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const leader = world.countries[0]
    if (selected) {
        return (
            <View style={styles.caption}>
                <Text style={styles.captionText} numberOfLines={1} testID="live-countries-selection">
                    {countryText(selected)} · {plural(selected.count, 'visitor')} ({selected.percent.toFixed(1)}%)
                </Text>
                <Pressable44
                    onPress={onClear}
                    accessibilityLabel="Clear the selected country"
                    pressedBackground={colors.pressed}
                    style={styles.clear}
                    testID="live-countries-clear"
                >
                    <Text style={styles.clearText}>Clear</Text>
                </Pressable44>
            </View>
        )
    }
    return (
        <View style={styles.caption}>
            <Text style={styles.captionText} numberOfLines={1}>
                {leader ? `${countryText(leader)} leads with ${plural(leader.count, 'visitor')}` : ''}
            </Text>
            <Text style={styles.hint}>Tap a country</Text>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    content: {
        paddingHorizontal: layout.inboxGutter,
    },
    titleBlock: {
        paddingHorizontal: 6,
        marginBottom: 12,
    },
    title: {
        ...type.screenTitle,
        fontSize: 26,
        lineHeight: 34,
        marginTop: 4,
        color: colors.ink,
    },
    statusRow: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
    },
    status: {
        ...type.meta,
        flexShrink: 1,
        lineHeight: 18,
        minHeight: 18,
        color: colors.tertiary,
        fontVariant: ['tabular-nums'],
    },
    mapBlock: {
        zIndex: 1,
        gap: 4,
        marginTop: -screenLayout.bottomPadding,
        paddingTop: screenLayout.bottomPadding,
        paddingBottom: 12,
        backgroundColor: colors.background,
    },
    caption: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
        minHeight: 36,
        paddingHorizontal: 6,
    },
    captionText: {
        ...type.meta,
        flexShrink: 1,
        color: colors.secondary,
    },
    hint: {
        ...type.meta,
        color: colors.tertiary,
    },
    clear: {
        height: 34,
        paddingHorizontal: 10,
        borderRadius: 8,
        justifyContent: 'center',
    },
    clearText: {
        ...type.buttonSmall,
        color: colors.blue,
    },
}))
