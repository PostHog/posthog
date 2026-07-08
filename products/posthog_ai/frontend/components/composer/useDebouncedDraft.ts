import { useEffect, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

export interface DebouncedDraft {
    /** Local echo to bind to `Composer.Root`'s `value` — updated synchronously on every keystroke. */
    value: string
    /** Bind to `Composer.Root`'s `onChange` — updates the local echo now, syncs upstream on a debounce. */
    onChange: (next: string) => void
    /** Wrap the caller's submit so the latest keystroke is flushed to the owning logic before it reads the draft. */
    submit: (send: () => void) => void
}

/**
 * Buffers a composer draft in local component state and debounces the write to the owning kea logic, so each
 * keystroke is an isolated, cheap re-render rather than a store dispatch that notifies every subscriber.
 * Binding the composer straight to kea made every keystroke re-render every subscriber — next to a mounted
 * thread/virtualizer that's what makes typing lag, and it grows with conversation length. kea stays the
 * source of truth: external changes (draft restore, clear-on-submit) are mirrored back, the pending value is
 * flushed synchronously before submit so the send never races the debounce, and any pending draft is flushed
 * on unmount. Mirrors the fix in `scenes/max/components/QuestionInput.tsx` for the same problem.
 */
export function useDebouncedDraft(
    externalValue: string,
    sync: (value: string) => void,
    delayMs = 150
): DebouncedDraft {
    const [value, setValue] = useState(externalValue)
    const debouncedSync = useDebouncedCallback(sync, delayMs)

    // Flush a pending draft on unmount so text typed just before teardown still persists to kea.
    useEffect(() => () => debouncedSync.flush(), [debouncedSync])

    // Mirror external changes (suggestion insertion, draft restore, clear-on-submit) into the local echo.
    // Cancel any in-flight keystroke sync first: an external write can land while a debounced sync from
    // prior typing is still pending, and without cancelling that stale sync fires ~150ms later and clobbers
    // the external value (e.g. type in the task composer, then click a suggestion). The debounce coalesces
    // to the latest keystroke and only fires once typing pauses, so its own write echoes back an equal value
    // here (a no-op cancel + no-op setValue) — cancelling never drops an in-progress keystroke.
    useEffect(() => {
        debouncedSync.cancel()
        setValue(externalValue)
    }, [externalValue, debouncedSync])

    return {
        value,
        onChange: (next: string): void => {
            setValue(next)
            debouncedSync(next)
        },
        submit: (send: () => void): void => {
            // Flush the pending keystroke synchronously so the send reads the latest draft, not the stale
            // debounced value; a no-op when nothing is pending (kea already has it).
            debouncedSync.flush()
            send()
        },
    }
}
