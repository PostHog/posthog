/**
 * `<SecretEditDialog />` — set, rotate, or clear a single secret on an
 * agent's encrypted env block.
 *
 * Mounted from `<ConnectionsTab>` when the URL carries `?edit_secret=KEY`
 * (and optionally `?callback_session=<id>`). Closing the dialog drops
 * both params via the parent's URL-state setter. On a successful save or
 * clear, dispatches `SECRET_SET_EVENT` so any listening surface (the
 * dock's chat runner) can react — that's the concierge callback path.
 *
 * The form is intentionally narrow:
 *   - One required field (`value`) for set; submit triggers PUT.
 *   - A "Clear" button for the rotate-then-revoke case; triggers DELETE.
 *   - The dialog never shows existing values (the API never returns them).
 *
 * The current set/unset status is fetched once when the dialog opens so
 * the user can see whether they're updating an existing key or creating
 * a new one; the value field stays blank either way.
 */

'use client'

import { useEffect, useState } from 'react'

import {
    Button,
    Dialog,
    DialogBody,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Input,
    Label,
} from '@posthog/quill'

import { useSessionTeamId } from '@/components/session-context'
import { ApiError, clearEnvKey, getEnvKey, setEnvKey, type EnvKeyStatus } from '@/lib/apiClient'
import { dispatchSecretSetEvent } from '@/lib/secretLinks'

export interface SecretEditDialogProps {
    agentSlug: string
    /** The secret name. When `null`, the dialog stays closed. */
    secret: string | null
    /** Echoed back through the callback event. */
    callbackSessionId: string | null
    /**
     * Whether the spec declares this secret. Determines the dialog copy
     * (an unknown / "ad hoc" key is allowed but flagged so the user
     * knows it won't be read by the agent unless they add it to the spec).
     */
    isDeclaredOnSpec: boolean
    /** Closes the dialog (parent owns the URL state). */
    onClose: () => void
    /**
     * Called after a successful set or clear so the parent can refetch
     * the env_keys list and update the set/unset chip in the row.
     */
    onMutated: () => void
}

type Mode = 'loading' | 'ready'

export function SecretEditDialog({
    agentSlug,
    secret,
    callbackSessionId,
    isDeclaredOnSpec,
    onClose,
    onMutated,
}: SecretEditDialogProps): React.ReactElement | null {
    const teamId = useSessionTeamId()!

    // Pre-fetched status so the dialog can label itself "Update" vs "Set".
    // Tolerate failures (network, 404) by falling back to "Set" — the
    // user can still submit; the API will create / overwrite either way.
    const [status, setStatus] = useState<EnvKeyStatus | null>(null)
    const [mode, setMode] = useState<Mode>('loading')
    const [value, setValue] = useState('')
    const [submitting, setSubmitting] = useState(false)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        if (!secret) {
            return
        }
        let cancelled = false
        setMode('loading')
        setStatus(null)
        setValue('')
        setError(null)
        void (async () => {
            try {
                const s = await getEnvKey(teamId, agentSlug, secret)
                if (cancelled) {
                    return
                }
                setStatus(s)
            } catch (err) {
                if (cancelled) {
                    return
                }
                // 404 → application missing — surface; everything else is
                // best-effort, fall through to "ready" without a status.
                if (err instanceof ApiError && err.status === 404) {
                    setError(err.message)
                }
            } finally {
                if (!cancelled) {
                    setMode('ready')
                }
            }
        })()
        return () => {
            cancelled = true
        }
    }, [teamId, agentSlug, secret])

    if (!secret) {
        return null
    }

    const isUpdate = status?.is_set === true

    const submitSet = async (): Promise<void> => {
        if (!value || submitting) {
            return
        }
        setSubmitting(true)
        setError(null)
        try {
            await setEnvKey(teamId, agentSlug, secret, value)
            // Fire the callback event first so the dock can react while
            // we're still on screen — then close + refetch.
            dispatchSecretSetEvent({
                agentSlug,
                secret,
                action: 'set',
                sessionId: callbackSessionId,
            })
            onMutated()
            onClose()
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err))
        } finally {
            setSubmitting(false)
        }
    }

    const submitClear = async (): Promise<void> => {
        if (submitting) {
            return
        }
        setSubmitting(true)
        setError(null)
        try {
            await clearEnvKey(teamId, agentSlug, secret)
            dispatchSecretSetEvent({
                agentSlug,
                secret,
                action: 'cleared',
                sessionId: callbackSessionId,
            })
            onMutated()
            onClose()
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err))
        } finally {
            setSubmitting(false)
        }
    }

    return (
        <Dialog open onOpenChange={(open) => !open && !submitting && onClose()}>
            <DialogContent>
                {/*
                 * The form wraps Header + Body + Footer so Enter submits
                 * from anywhere; the spacing slots come from quill's
                 * Dialog primitives (Body provides the px/py the middle
                 * area needs, Header / Footer keep their own padding).
                 */}
                <form
                    onSubmit={(e) => {
                        e.preventDefault()
                        void submitSet()
                    }}
                >
                    <DialogHeader>
                        <DialogTitle>{isUpdate ? 'Rotate secret' : 'Set secret'}</DialogTitle>
                        <DialogDescription>
                            <span className="font-mono text-foreground">{secret}</span>
                            {!isDeclaredOnSpec ? (
                                <span className="ml-2 rounded-full border border-warning-foreground/30 bg-warning/30 px-1.5 py-0.5 text-[0.625rem] uppercase tracking-wide text-warning-foreground">
                                    not in spec
                                </span>
                            ) : null}
                            <span className="block pt-1.5 text-xs text-muted-foreground">
                                Stored encrypted on the application. The agent decrypts it at session start; the value
                                is never read back through the API.
                            </span>
                        </DialogDescription>
                    </DialogHeader>

                    <DialogBody render={<div />} className="space-y-4 px-6 py-4 text-sm">
                        <div className="space-y-1.5">
                            <Label htmlFor="secret-value" className="text-xs">
                                {isUpdate ? 'New value' : 'Value'}
                            </Label>
                            <Input
                                id="secret-value"
                                type="password"
                                autoComplete="off"
                                spellCheck={false}
                                autoFocus
                                value={value}
                                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setValue(e.currentTarget.value)}
                                placeholder={mode === 'loading' ? 'Loading…' : 'paste secret value'}
                                disabled={submitting || mode === 'loading'}
                            />
                            {isUpdate ? (
                                <p className="text-[0.6875rem] text-muted-foreground">
                                    A value is already set — submitting will rotate it.
                                </p>
                            ) : null}
                        </div>

                        {error ? <p className="text-xs text-destructive-foreground">{error}</p> : null}

                        {callbackSessionId ? (
                            <p className="rounded-md border border-info-foreground/30 bg-info/20 px-2.5 py-1.5 text-[0.6875rem] text-info-foreground">
                                An agent session is waiting on this. Saving here will let it resume.
                            </p>
                        ) : null}
                    </DialogBody>

                    <DialogFooter className="flex-row justify-between">
                        <div>
                            {isUpdate ? (
                                <Button
                                    type="button"
                                    variant="outline"
                                    onClick={submitClear}
                                    disabled={submitting}
                                    aria-busy={submitting ? 'true' : undefined}
                                >
                                    Clear
                                </Button>
                            ) : null}
                        </div>
                        <div className="flex gap-2">
                            <DialogClose render={<Button variant="outline" type="button" disabled={submitting} />}>
                                Cancel
                            </DialogClose>
                            <Button
                                type="submit"
                                disabled={!value || submitting || mode === 'loading'}
                                aria-busy={submitting ? 'true' : undefined}
                            >
                                {submitting ? 'Saving…' : isUpdate ? 'Rotate' : 'Save'}
                            </Button>
                        </div>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    )
}
