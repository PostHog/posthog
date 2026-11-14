import { useRouter } from 'expo-router'
import type { ReactElement } from 'react'
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

interface LiveMapCardProps {
    users?: boolean
    mobileOnly?: boolean
    webOnly?: boolean
    world: LiveWorld | null
    /** Live's Pause. Visitors by country follows it, and Pause cannot change while that screen covers Live. */
    paused: boolean
}

/** Visitors per country on a world map. The card opens Visitors by country. */
export function LiveMapCard({
    world,
    paused,
    users = false,
    mobileOnly = false,
    webOnly = false,
}: LiveMapCardProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const router = useRouter()
    const openCountries = (): void => {
        useLiveWorldShare.setState({ world, paused, users, mobileOnly, webOnly })
        trackLiveMapOpened()
        router.push(liveCountriesHref())
    }

    const leader = world?.countries[0]
    const title = users ? 'Where users are' : 'Where visitors are'
    if (!world || !leader) {
        return (
            <LiveCard title={title} testID="live-map">
                <LiveCardNote
                    text={world ? 'No country data' : NOT_LOADED_TEXT}
                    testID={world ? 'live-map-empty' : 'live-map-not-loaded'}
                />
            </LiveCard>
        )
    }
    const countries = plural(world.countries.length, 'country', 'countries')
    return (
        <LiveCard onPress={openCountries} accessibilityLabel={`${title}, ${countries}`} testID="live-map">
            <View style={styles.head}>
                <View style={styles.headText}>
                    <Text style={styles.title}>{title}</Text>
                    <Text style={styles.meta}>{countries} · last 30 minutes</Text>
                </View>
                <ChevronRightIcon size={iconSizes.small} color={colors.tertiary} />
            </View>
            <WorldMap counts={world.counts} testID="live-map-canvas" />
            <Text style={styles.caption} numberOfLines={1}>
                {countryText(leader)} leads with {plural(leader.count, users ? 'user' : 'visitor')}
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
