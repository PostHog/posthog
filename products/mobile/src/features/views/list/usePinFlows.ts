import { useCallback, useMemo } from 'react'

import { toError } from '@/lib/errors'
import type { PinView, ViewRef } from '@/model/views'

import type { PinSource } from '../analytics'
import type { PinActions } from '../pinHooks'
import type { PinTarget } from '../shortcutInput'
import { type ToastMessage, useToasts } from '../ViewsToast'
import { pinTargetFor } from './viewMeta'

export interface PinFlows {
    /** False for kinds only the web can pin. */
    canPin: (view: Pick<ViewRef, 'kind' | 'ref' | 'name'>) => boolean
    /** Pins or unpins a Recent, Browse or search row, with a toast that can undo it. */
    togglePin: (view: Pick<ViewRef, 'kind' | 'ref' | 'name'>, from: PinSource) => void
    /** Unpins a pin, with a toast that can pin it again. */
    unpin: (pin: PinView, from: PinSource) => void
    toast: ToastMessage | null
    hideToast: () => void
}

/**
 * Pin and unpin as the list, Browse and search use them. A failure shows the data layer's message in a toast; the
 * list has already rolled the change back.
 */
export function usePinFlows(actions: PinActions): PinFlows {
    const toasts = useToasts()
    const { show } = toasts
    const { pin: pinTarget, unpin: unpinTarget, isPinned } = actions

    const fail = useCallback((error: unknown) => show(toError(error).message), [show])

    const pinWithUndo = useCallback(
        (target: PinTarget, from: PinSource) => {
            pinTarget(target, from)
                .then(() => show('Pinned to Views', () => unpinTarget(target, 'undo').catch(fail)))
                .catch(fail)
        },
        [pinTarget, unpinTarget, show, fail]
    )

    const unpinWithUndo = useCallback(
        (view: PinView | PinTarget, name: string, target: PinTarget | null, from: PinSource) => {
            unpinTarget(view, from)
                .then(() => show(`Unpinned ${name}`, target ? () => pinTarget(target, 'undo').catch(fail) : undefined))
                .catch(fail)
        },
        [pinTarget, unpinTarget, show, fail]
    )

    return useMemo<PinFlows>(
        () => ({
            canPin: (view) => pinTargetFor(view) !== null,
            togglePin: (view, from) => {
                const target = pinTargetFor(view)
                if (!target) {
                    return
                }
                if (isPinned(target)) {
                    unpinWithUndo(target, view.name, target, from)
                } else {
                    pinWithUndo(target, from)
                }
            },
            unpin: (pin, from) => unpinWithUndo(pin, pin.name, pinTargetFor(pin), from),
            toast: toasts.toast,
            hideToast: toasts.hide,
        }),
        [isPinned, pinWithUndo, unpinWithUndo, toasts.toast, toasts.hide]
    )
}
