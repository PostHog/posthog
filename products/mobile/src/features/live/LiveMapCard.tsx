import { useRouter } from 'expo-router'
import { type ReactElement, useCallback } from 'react'
import { Text, View } from 'react-native'

import { liveCountriesHref } from '@/features/views/viewRoutes'
import { plural } from '@/model/adapters/text'
import type { LiveWorld } from '@/model/live'
import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, type } from '@/ui/tokens'

import { trackLiveMapOpened } from './analytics'
import { LiveCard, LiveCardNote, NOT_LOADED_TEXT } from './LiveCard'
import { countryText } from './liveFormat'
import { useLiveWorldShare } from './liveWorldStore'
import { WorldMap } from './map/WorldMap'

const TITLE = 'Where visitors are'

interface LiveMapCardProps {
    world: LiveWorld | null
    /** Live's Pause. Visitors by country follows it, and Pause cannot change while that screen covers Live. */
    paused: boolean
}

/** Visitors per country on a world map. The card, or a country on its map, opens Visitors by country. */
export function LiveMapCard({ world, paused }: LiveMapCardProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const router = useRouter()
    const openCountry = useCallback(
        (code: string | null): void => {
            useLiveWorldShare.setState({ world, paused })
            trackLiveMapOpened({ from: code ? 'map_country' : 'card' })
            router.push(liveCountriesHref(code))
        },
        [router, world, paused]
    )

    const leader = world?.countries[0]
    if (!world || !leader) {
        return (
            <LiveCard title={TITLE} testID="live-map">
                <LiveCardNote
                    text={world ? 'No country data' : NOT_LOADED_TEXT}
                    testID={world ? 'live-map-empty' : 'live-map-not-loaded'}
                />
            </LiveCard>
        )
    }
    const countries = plural(world.countries.length, 'country', 'countries')
    return (
        <LiveCard onPress={() => openCountry(null)} accessibilityLabel={`${TITLE}, ${countries}`} testID="live-map">
            <View style={styles.head}>
                <View style={styles.headText}>
                    <Text style={styles.title}>{TITLE}</Text>
                    <Text style={styles.meta}>{countries} · last 30 minutes</Text>
                </View>
                <ChevronRightIcon size={iconSizes.small} color={colors.tertiary} />
            </View>
            <WorldMap counts={world.counts} onSelect={openCountry} testID="live-map-canvas" />
            <Text style={styles.caption} numberOfLines={1}>
                {countryText(leader)} leads with {plural(leader.count, 'visitor')}
            </Text>
        </LiveCard>
    )
}

const useStyles = createStyles(({ colors }) => ({
    head: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
    },
    headText: {
        flex: 1,
        gap: 2,
    },
    title: {
        ...type.bodySmallStrong,
        color: colors.ink,
    },
    meta: {
        ...type.meta,
        color: colors.tertiary,
    },
    caption: {
        ...type.meta,
        color: colors.secondary,
    },
}))
