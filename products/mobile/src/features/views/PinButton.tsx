import { type ReactElement, useRef } from 'react'
import { StyleSheet } from 'react-native'

import { toError } from '@/lib/errors'
import { shortcutMatchKey } from '@/model/adapters/viewPins'
import type { PinView } from '@/model/views'
import { PinIcon } from '@/ui/icons/PinIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { useColors } from '@/ui/theme'

import type { PinSource } from './analytics'
import { usePinActions, usePins } from './pinHooks'
import type { PinTarget } from './shortcutInput'
import { useToasts, ViewsToast } from './ViewsToast'

export interface PinMatch {
    kind: 'dashboard' | 'insight' | 'web_analytics'
    /** The view's own ref: the dashboard id as a string (the demo ref in demo mode), the insight `short_id`. */
    ref: string | null
}

interface PinButtonProps {
    /** What a pin writes. Null until the view has loaded its id and name. */
    target: PinTarget | null
    /** How the pin list finds this view. A dashboard pin matches by its ref, which differs from the id in demo mode. */
    match: PinMatch
}

/**
 * The pin beside a view's title. It pins and unpins through the shared pin list, so the Views list and the web's
 * Starred items follow at once. A toast confirms each change and offers Undo.
 */
export function PinButton({ target, match }: PinButtonProps): ReactElement {
    const colors = useColors()
    const actions = usePinActions()
    const { pins } = usePins()
    const key = shortcutMatchKey(match.kind, match.ref)
    const pinView = pins.data?.find((pin) => shortcutMatchKey(pin.type, pin.ref) === key)
    const pinned = Boolean(pinView)
    const { toast, show, hide } = useToasts()
    // Undo runs after the list changed, so it reads the latest pin, not the one from the render that showed the toast.
    const latest = useRef<{ pinView: PinView | undefined; target: PinTarget | null }>({ pinView, target })
    latest.current = { pinView, target }

    const pin = async (from: PinSource): Promise<void> => {
        const current = latest.current.target
        if (!current) {
            return
        }
        try {
            await actions.pin(current, from)
            show('Pinned to Views', () => void unpin('undo'))
        } catch (error) {
            show(toError(error).message)
        }
    }

    const unpin = async (from: PinSource): Promise<void> => {
        const view = latest.current.pinView ?? latest.current.target
        if (!view) {
            return
        }
        try {
            await actions.unpin(view, from)
            if (from !== 'undo') {
                show('Unpinned from Views', () => void pin('undo'))
            } else {
                hide()
            }
        } catch (error) {
            show(toError(error).message)
        }
    }

    return (
        <>
            <Pressable44
                onPress={() => void (pinned ? unpin('header') : pin('header'))}
                disabled={!target || actions.pending || pins.isLoading}
                accessibilityLabel={pinned ? 'Unpin from Views' : 'Pin to Views'}
                accessibilityState={{ selected: pinned, disabled: !target || actions.pending }}
                pressedBackground={colors.sunken}
                style={styles.button}
                testID="view-pin"
            >
                <PinIcon size={22} filled={pinned} color={pinned ? colors.blue : colors.secondary} />
            </Pressable44>
            <ViewsToast toast={toast} onHide={hide} bottom={34} />
        </>
    )
}

const styles = StyleSheet.create({
    button: {
        width: 40,
        height: 40,
        borderRadius: 999,
        alignItems: 'center',
        justifyContent: 'center',
    },
})
