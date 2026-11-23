import { useRouter } from 'expo-router'
import { Fragment, type ReactElement } from 'react'
import { Text, View } from 'react-native'

import { DeltaPill } from '@/features/views/DeltaPill'
import { ViewIcon } from '@/features/views/list/viewMeta'
import { usePinGlance } from '@/features/views/usePinGlance'
import type { PinView } from '@/model/views'
import { Sparkline } from '@/ui/chart/Sparkline'
import { Eyebrow } from '@/ui/Eyebrow'
import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { InboxIcon } from '@/ui/icons/InboxIcon'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import { trackLiveMeanwhileOpened } from './analytics'
import { LiveMeanwhileRow } from './LiveMeanwhileRow'
import { useLiveMeanwhile } from './useLiveMeanwhile'

function unreadText(unread: number | null): string | null {
    if (unread === null) {
        return null
    }
    return unread === 0 ? 'Nothing unread' : `${unread} unread`
}

/** Pinned views and the inbox, so a Live with nothing to show still leads somewhere useful. */
export function LiveMeanwhile(): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const router = useRouter()
    const { pins, unread } = useLiveMeanwhile()
    const openInbox = (): void => {
        trackLiveMeanwhileOpened({ target: 'inbox' })
        router.navigate('/(tabs)/inbox')
    }
    const inboxSubtitle = unreadText(unread)
    return (
        <View style={styles.section} testID="live-meanwhile">
            <View style={styles.eyebrow}>
                <Eyebrow>Meanwhile</Eyebrow>
            </View>
            <View style={styles.card}>
                {pins.map((pin) => (
                    <Fragment key={pin.shortcutId}>
                        <PinRow pin={pin} />
                        <View style={styles.divider} />
                    </Fragment>
                ))}
                <LiveMeanwhileRow
                    icon={<InboxIcon size={18} color={colors.muted} />}
                    title="Inbox"
                    subtitle={inboxSubtitle}
                    accessibilityLabel={['Inbox', inboxSubtitle].filter(Boolean).join(', ')}
                    onPress={openInbox}
                    testID="live-meanwhile-inbox"
                    trailing={
                        <View style={styles.inboxEnd}>
                            {unread ? <View style={styles.unreadDot} /> : null}
                            <ChevronRightIcon size={13} color={colors.tertiary} />
                        </View>
                    }
                />
            </View>
        </View>
    )
}

/** A pin with the number, change and sparkline the Views list last read for it, or a chevron when it has none. */
function PinRow({ pin }: { pin: PinView }): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const router = useRouter()
    const glance = usePinGlance(pin, 'live_meanwhile')
    const value = glance.hasNumber ? glance.value : null
    const { delta, sparkline } = glance
    const open = (): void => {
        if (glance.href) {
            trackLiveMeanwhileOpened({ target: 'view' })
            router.push(glance.href)
        }
    }
    return (
        <LiveMeanwhileRow
            icon={<ViewIcon kind={pin.kind} />}
            title={pin.name}
            subtitle={glance.subtitle}
            accessibilityLabel={[pin.name, value, value ? delta?.spoken : null, glance.subtitle]
                .filter(Boolean)
                .join(', ')}
            onPress={open}
            testID={`live-meanwhile-pin-${pin.kind}-${pin.ref}`}
            trailing={
                value !== null ? (
                    <>
                        {sparkline.values.length > 1 ? (
                            <Sparkline
                                values={sparkline.values}
                                highlightFrom={sparkline.highlightFrom}
                                width={56}
                                height={28}
                            />
                        ) : null}
                        <View style={styles.value}>
                            <Text style={styles.number} numberOfLines={1} testID={`live-meanwhile-value-${pin.ref}`}>
                                {value}
                            </Text>
                            {delta ? <DeltaPill {...delta.props} /> : null}
                        </View>
                    </>
                ) : (
                    <ChevronRightIcon size={13} color={colors.tertiary} />
                )
            }
        />
    )
}
const useStyles = createStyles(({ colors }) => ({
    section: {
        gap: 10,
    },
    eyebrow: {
        paddingHorizontal: 6,
        marginTop: 8,
    },
    card: {
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
        overflow: 'hidden',
    },
    divider: {
        height: 1,
        backgroundColor: colors.hairline,
    },
    value: {
        alignItems: 'flex-end',
        gap: 4,
    },
    number: {
        ...type.sheetTitle,
        color: colors.ink,
        fontVariant: ['tabular-nums'],
    },
    inboxEnd: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
    },
    unreadDot: {
        width: 8,
        height: 8,
        borderRadius: 4,
        backgroundColor: colors.blue,
    },
}))
