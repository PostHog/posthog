import { useRouter } from 'expo-router'
import { Fragment, type ReactElement, useCallback } from 'react'
import { Text, View } from 'react-native'

import { DeltaPill, deltaSpoken } from '@/features/views/DeltaPill'
import { ViewIcon, viewTypeLabel } from '@/features/views/list/viewMeta'
import { usePinData } from '@/features/views/pinHooks'
import { deltaBasisText, snapshotFormatter } from '@/features/views/snapshotChart'
import { viewHref } from '@/features/views/viewRoutes'
import type { PinView } from '@/model/views'
import { Sparkline } from '@/ui/chart/Sparkline'
import { Eyebrow } from '@/ui/Eyebrow'
import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { InboxIcon } from '@/ui/icons/InboxIcon'
import { createStyles, useColors } from '@/ui/theme'
import { radii } from '@/ui/tokens'

import { trackLiveMeanwhileOpened } from './analytics'
import { LiveMeanwhileRow } from './LiveMeanwhileRow'
import { useLiveMeanwhile } from './useLiveMeanwhile'

/** The Number pin's sparkline buckets, and the last 7 of them in blue, as the Views list draws them. */
const SPARKLINE_BUCKETS = 14
const SPARKLINE_CURRENT = 7

/** Pinned views and the inbox, so a Live with nothing to show still leads somewhere useful. */
export function LiveMeanwhile(): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const router = useRouter()
    const { pins, unread } = useLiveMeanwhile()
    const openPin = useCallback(
        (pin: PinView) => {
            const href = viewHref(pin, { from: 'pinned', mode: pin.display.mode })
            if (href) {
                trackLiveMeanwhileOpened({ target: 'view' })
                router.push(href)
            }
        },
        [router]
    )
    const openInbox = (): void => {
        trackLiveMeanwhileOpened({ target: 'inbox' })
        router.navigate('/(tabs)/inbox')
    }
    const unreadText = unread === null ? null : `${unread} unread`
    return (
        <View style={styles.section} testID="live-meanwhile">
            <View style={styles.eyebrow}>
                <Eyebrow>Meanwhile</Eyebrow>
            </View>
            <View style={styles.card}>
                {pins.map((pin) => (
                    <Fragment key={pin.shortcutId}>
                        <PinRow pin={pin} onOpen={openPin} />
                        <View style={styles.divider} />
                    </Fragment>
                ))}
                <LiveMeanwhileRow
                    icon={<InboxIcon size={18} color={colors.muted} />}
                    title="Inbox"
                    subtitle={unreadText}
                    accessibilityLabel={['Inbox', unreadText].filter(Boolean).join(', ')}
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
function PinRow({ pin, onOpen }: { pin: PinView; onOpen: (pin: PinView) => void }): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const { snapshot } = usePinData(pin)
    const subtitle = pin.kind === 'dashboard' && snapshot ? snapshot.name : viewTypeLabel(pin.kind)
    const format = snapshot ? snapshotFormatter(snapshot) : null
    const value =
        snapshot && format && snapshot.capabilities.number && snapshot.value !== null ? format(snapshot.value) : null
    const delta = value !== null && snapshot?.delta ? snapshot.delta : null
    const basis = delta && snapshot ? deltaBasisText(delta, snapshot.interval) : ''
    const values =
        value !== null ? (snapshot?.series?.points ?? []).slice(-SPARKLINE_BUCKETS).map((point) => point.value) : []
    const spoken = delta && format ? deltaSpoken(delta, format, basis) : null
    return (
        <LiveMeanwhileRow
            icon={<ViewIcon kind={pin.kind} />}
            title={pin.name}
            subtitle={subtitle}
            accessibilityLabel={[pin.name, value, spoken, subtitle].filter(Boolean).join(', ')}
            onPress={() => onOpen(pin)}
            testID={`live-meanwhile-pin-${pin.kind}-${pin.ref}`}
            trailing={
                value !== null ? (
                    <>
                        {values.length > 1 ? (
                            <Sparkline
                                values={values}
                                highlightFrom={values.length - SPARKLINE_CURRENT}
                                width={56}
                                height={28}
                            />
                        ) : null}
                        <View style={styles.value}>
                            <Text style={styles.number} numberOfLines={1}>
                                {value}
                            </Text>
                            {delta && format ? <DeltaPill delta={delta} formatValue={format} basis={basis} /> : null}
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
        fontSize: 18,
        lineHeight: 22,
        fontWeight: '700',
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
