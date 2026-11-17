import { type ReactElement, useEffect } from 'react'
import { Text, useWindowDimensions, View } from 'react-native'
import Animated, { useAnimatedScrollHandler } from 'react-native-reanimated'

import { useViewBack, ViewScreenFrame } from '@/features/views/screen/ViewScreenFrame'
import { ViewSkeleton } from '@/features/views/screen/ViewSkeleton'
import { useViewsContext } from '@/features/views/useViewsContext'
import { ViewsReauthState } from '@/features/views/ViewsReauthState'
import { plural } from '@/model/adapters/text'
import type { LiveWorld } from '@/model/live'
import { Eyebrow } from '@/ui/Eyebrow'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { LiveDot } from '@/ui/LiveDot'
import { ScreenChrome } from '@/ui/ScreenChrome'
import { StateView } from '@/ui/StateView'
import { SCREEN_CONTENT_TOP } from '@/ui/screenLayout'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, layout, type } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets } from '@/ui/useScreenInsets'
import { type ScrollTitleState, useScrollTitle } from '@/ui/useScrollTitle'

import { useLiveWorld } from './hooks'
import { LiveCardNote } from './LiveCard'
import { LiveCountryList } from './LiveCountryList'
import type { LiveStatus } from './liveController'
import { countriesStatusText, countryText } from './liveFormat'
import { clearLiveWorldShare, useLiveWorldShare } from './liveWorldStore'
import { WORLD_ASPECT_RATIO } from './map/mapGeometry'
import { WorldMap } from './map/WorldMap'

/** Limit the map's height so the country list is visible in landscape. */
const MAP_MAX_HEIGHT_SHARE = 0.4

export function LiveCountriesScreen(): ReactElement {
    const { access, identity } = useViewsContext()
    const users = useLiveWorldShare((share) => share.users)
    const scrollTitle = useScrollTitle(users ? 'Users by country' : 'Visitors by country')
    const back = useViewBack()
    return (
        <ViewScreenFrame
            // Back only: the screen has no actions of its own, so it leaves out View chrome's More button.
            chrome={<ScreenChrome onBack={back} backTestID="view-back" title={scrollTitle.title} />}
        >
            {access.state === 'ok' ? (
                <CountriesBody key={identity} scrollTitle={scrollTitle} />
            ) : (
                <ViewsReauthState access={access} />
            )}
        </ViewScreenFrame>
    )
}

function CountriesBody({ scrollTitle }: { scrollTitle: ScrollTitleState }): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const insets = useScreenInsets()
    const { height: windowHeight } = useWindowDimensions()
    const feed = useLiveWorld()
    const { world } = feed
    const users = useLiveWorldShare((share) => share.users) ?? false
    useEffect(() => clearLiveWorldShare, [])

    const contentTop = topOffset(insets, SCREEN_CONTENT_TOP)
    const scrollY = scrollTitle.title.scrollY
    const onScroll = useAnimatedScrollHandler((event) => {
        scrollY.value = event.contentOffset.y
    })
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
                <View style={styles.mapBlock}>
                    <View
                        style={[
                            styles.mapFrame,
                            { maxWidth: windowHeight * MAP_MAX_HEIGHT_SHARE * WORLD_ASPECT_RATIO },
                        ]}
                    >
                        <WorldMap counts={world.counts} testID="live-countries-map" />
                    </View>
                    <MapCaption world={world} users={users} />
                </View>
                <LiveCountryList countries={world.countries} users={users} />
            </>
        )
    }

    return (
        <Animated.ScrollView
            contentContainerStyle={[
                styles.content,
                { paddingTop: contentTop, paddingBottom: bottomOffset(insets, 48) },
            ]}
            onScroll={onScroll}
            scrollEventThrottle={16}
            testID="live-countries-scroll"
        >
            <CountriesTitle
                world={world}
                status={feed.status}
                screenActive={feed.screenActive}
                onTitleLayout={scrollTitle.onTitleLayout}
                users={users}
            />
            {content}
        </Animated.ScrollView>
    )
}

interface CountriesTitleProps {
    users: boolean
    world: LiveWorld | null
    status: LiveStatus
    screenActive: boolean
    onTitleLayout: ScrollTitleState['onTitleLayout']
}

function CountriesTitle({ world, status, screenActive, onTitleLayout, users }: CountriesTitleProps): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.titleBlock}>
            <View onLayout={onTitleLayout}>
                <Eyebrow>Live</Eyebrow>
                <Text style={styles.title} accessibilityRole="header">
                    {users ? 'Users by country' : 'Visitors by country'}
                </Text>
            </View>
            <View style={styles.statusRow}>
                <LiveDot on={status === 'live'} animate={screenActive} />
                <Text style={styles.status} accessibilityLiveRegion="polite" testID="live-countries-status">
                    {countriesStatusText(status, world, users)}
                </Text>
            </View>
        </View>
    )
}

function MapCaption({ world, users }: { world: LiveWorld; users: boolean }): ReactElement {
    const styles = useStyles()
    const leader = world.countries[0]
    return (
        <View style={styles.caption}>
            <Text style={styles.captionText} numberOfLines={1}>
                {leader ? `${countryText(leader)} leads with ${plural(leader.count, users ? 'user' : 'visitor')}` : ''}
            </Text>
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
    mapFrame: {
        width: '100%',
        alignSelf: 'center',
    },
    mapBlock: {
        gap: 4,
        paddingBottom: 12,
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
}))
