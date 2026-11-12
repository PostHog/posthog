import * as Clipboard from 'expo-clipboard'
import { useRouter } from 'expo-router'
import type { ReactElement } from 'react'
import { Linking, Text, View } from 'react-native'

import type { ProjectScope } from '@/api/reports'
import { sessionWebUrl } from '@/features/replay/replayLinks'
import { SheetTitle } from '@/features/views/screen/SheetTitle'
import { viewWebUrl } from '@/features/views/webLinks'
import { formatClock } from '@/lib/dates'
import { FEATURE_FLAGS, useFeatureFlag } from '@/lib/featureFlags'
import { safeHttpsUrl } from '@/lib/urls'
import { useNow } from '@/lib/useNow'
import type { LiveEventRow } from '@/model/live'
import { BottomSheet } from '@/ui/BottomSheet'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { PlayIcon } from '@/ui/icons/PlayIcon'
import { MonoText } from '@/ui/MonoText'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import { trackLiveEventActionTaken } from './analytics'
import { agoText } from './liveFormat'

interface LiveEventSheetProps {
    visible: boolean
    screenActive: boolean
    /** Stays set while the sheet closes, so its content does not vanish mid-animation. */
    event: LiveEventRow | null
    /** Null in demo mode, where no person or recording exists on the web. */
    scope: ProjectScope | null
    onClose: () => void
    onNotice: (text: string) => void
}

export function LiveEventSheet({
    visible,
    screenActive,
    event,
    scope,
    onClose,
    onNotice,
}: LiveEventSheetProps): ReactElement {
    const colors = useColors()
    return (
        <BottomSheet
            visible={visible && event !== null}
            onClose={onClose}
            backgroundColor={colors.background}
            accessibilityLabel="Event details"
            testID="live-event-sheet"
        >
            {event ? (
                <EventDetails
                    event={event}
                    scope={scope}
                    onClose={onClose}
                    onNotice={onNotice}
                    active={visible && screenActive}
                />
            ) : null}
        </BottomSheet>
    )
}

function EventDetails({
    event,
    scope,
    active,
    onClose,
    onNotice,
}: {
    event: LiveEventRow
    active: boolean
    scope: ProjectScope | null
    onClose: () => void
    onNotice: (text: string) => void
}): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const router = useRouter()
    const now = useNow(active ? 10_000 : null).getTime()
    const replayInApp = useFeatureFlag(FEATURE_FLAGS.sessionReplay)
    const known = Number.isFinite(event.at)
    const subtitle = known ? `${formatClock(new Date(event.at))} · ${agoText(event.at, now)}` : null
    const personUrl = event.distinctId
        ? viewWebUrl(scope, `/person/${encodeURIComponent(event.distinctId)}`)
        : undefined
    const safePersonUrl = personUrl ? safeHttpsUrl(personUrl) : undefined
    const sessionId = event.sessionId

    const copyDistinctId = async (): Promise<void> => {
        trackLiveEventActionTaken({ action: 'copy_distinct_id' })
        try {
            const copied = await Clipboard.setStringAsync(event.distinctId)
            onNotice(copied ? 'Distinct ID copied' : "Couldn't copy the distinct ID. Try again.")
        } catch {
            onNotice("Couldn't copy the distinct ID. Try again.")
        }
    }
    const watchRecording = (): void => {
        if (!sessionId) {
            return
        }
        trackLiveEventActionTaken({ action: 'watch_recording' })
        onClose()
        if (replayInApp) {
            router.push({ pathname: '/replay/[sessionId]', params: { sessionId, source: 'other' } })
            return
        }
        const url = sessionWebUrl(scope, sessionId)
        const safe = url ? safeHttpsUrl(url) : undefined
        if (safe) {
            Linking.openURL(safe).catch(() => undefined)
        }
    }
    const viewPerson = (): void => {
        if (!safePersonUrl) {
            return
        }
        trackLiveEventActionTaken({ action: 'view_person' })
        Linking.openURL(safePersonUrl).catch(() => undefined)
        onClose()
    }

    const demo = scope === null
    return (
        <View>
            <SheetTitle title={event.label} subtitle={subtitle} onDone={onClose} />
            <View style={styles.card}>
                <View style={styles.row}>
                    <Text style={styles.key}>Person</Text>
                    <MonoText style={styles.value} numberOfLines={1} ellipsizeMode="middle">
                        {event.distinctId || '–'}
                    </MonoText>
                    {event.distinctId ? (
                        <Pressable44
                            onPress={copyDistinctId}
                            accessibilityLabel="Copy distinct ID"
                            pressedBackground={colors.pressed}
                            style={styles.action}
                            testID="live-event-copy"
                        >
                            <Text style={styles.actionText}>Copy</Text>
                        </Pressable44>
                    ) : null}
                </View>
                {event.url || event.place ? (
                    <View style={[styles.row, styles.divided]}>
                        <Text style={styles.key}>{event.kind === 'screen' ? 'Screen' : 'URL'}</Text>
                        <Text style={styles.text} numberOfLines={2} selectable>
                            {event.url ?? event.place}
                        </Text>
                    </View>
                ) : null}
                {sessionId ? (
                    <View style={[styles.row, styles.divided]}>
                        <Text style={styles.key}>Session</Text>
                        <MonoText style={styles.value} numberOfLines={1} ellipsizeMode="middle">
                            {sessionId}
                        </MonoText>
                        <Pressable44
                            onPress={watchRecording}
                            disabled={demo}
                            accessibilityLabel="Watch recording"
                            accessibilityState={{ disabled: demo }}
                            pressedBackground={colors.pressed}
                            style={styles.action}
                            testID="live-event-recording"
                        >
                            <PlayIcon size={10} color={demo ? colors.disabled : colors.blue} />
                            <Text style={[styles.actionText, demo && styles.disabled]}>Watch recording</Text>
                        </Pressable44>
                    </View>
                ) : null}
            </View>
            <Pressable44
                onPress={viewPerson}
                disabled={!safePersonUrl}
                accessibilityLabel="View person on web"
                accessibilityState={{ disabled: !safePersonUrl }}
                pressedBackground={colors.pressed}
                style={[styles.card, styles.link]}
                testID="live-event-person"
            >
                <View style={styles.linkText}>
                    <Text style={[styles.linkLabel, !safePersonUrl && styles.disabled]}>View person on web</Text>
                    {demo ? <Text style={styles.sub}>Not available in the demo</Text> : null}
                </View>
                <ExternalLinkIcon size={18} color={safePersonUrl ? colors.secondary : colors.disabled} />
            </Pressable44>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    card: {
        marginTop: 8,
        paddingHorizontal: 14,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
    },
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        minHeight: 52,
        paddingVertical: 8,
    },
    divided: {
        borderTopWidth: 1,
        borderTopColor: colors.rowDivider,
    },
    key: {
        ...type.meta,
        width: 64,
        color: colors.tertiary,
    },
    value: {
        flex: 1,
        minWidth: 0,
    },
    text: {
        ...type.metaSmall,
        flex: 1,
        color: colors.ink,
    },
    action: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
        minHeight: 36,
        paddingHorizontal: 6,
        borderRadius: radii.markSmall,
    },
    actionText: {
        ...type.buttonSmall,
        color: colors.blue,
    },
    disabled: {
        color: colors.disabled,
    },
    link: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        minHeight: 56,
    },
    linkText: {
        flex: 1,
    },
    linkLabel: {
        ...type.label,
        color: colors.ink,
    },
    sub: {
        ...type.metaSmall,
        color: colors.tertiary,
    },
}))
