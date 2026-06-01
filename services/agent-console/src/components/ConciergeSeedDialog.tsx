/**
 * `<ConciergeSeedDialog>` — modal shown when an `<EditWithAIButton>`
 * fires while a concierge session is already in progress. The user
 * picks between continuing the existing chat (appends the prompt to
 * the running session) or starting fresh (resets the runner then
 * sends).
 *
 * Mounted once at the dock layer. The seed is observed from the dock
 * store; the actual reset + send wires through props from the runner.
 */

'use client'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@posthog/quill'

import { useDockStore } from './dock-context'

export interface ConciergeSeedDialogProps {
    /** Whether the host runner has any turns to preserve. When false,
     *  the dock should auto-execute without showing the dialog at all
     *  — this component only renders when the user has a choice. */
    hasActiveTurns: boolean
    /** Reset the runner + start a fresh session, then send the prompt. */
    onStartFresh: () => void
    /** Send the prompt as the next user turn in the running session. */
    onContinue: () => void
}

export function ConciergeSeedDialog({
    hasActiveTurns,
    onStartFresh,
    onContinue,
}: ConciergeSeedDialogProps): React.ReactElement | null {
    const { conciergeSeed, cancelConciergeSeed } = useDockStore()

    // The dialog only matters in the "user has a choice" window — a
    // pending seed AND there's a running session. Empty-session and
    // already-confirmed seeds are handled upstream.
    const showing = conciergeSeed?.stage === 'pending' && hasActiveTurns

    if (!showing || !conciergeSeed) {
        return null
    }

    const handleStart = (): void => {
        onStartFresh()
    }
    const handleContinue = (): void => {
        onContinue()
    }
    const handleCancel = (): void => {
        cancelConciergeSeed()
    }

    return (
        <Dialog open onOpenChange={(open) => !open && handleCancel()}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Start a new conversation?</DialogTitle>
                    <DialogDescription>You already have a chat in progress with the concierge.</DialogDescription>
                </DialogHeader>
                <DialogBody render={<div />} className="space-y-2 px-6 py-4 text-sm">
                    <p>What would you like to do with this prompt?</p>
                    <blockquote className="rounded-md border-l-2 border-border bg-muted/20 px-3 py-2 text-xs italic text-muted-foreground">
                        {conciergeSeed.prompt}
                    </blockquote>
                </DialogBody>
                <DialogFooter className="flex-row justify-between">
                    <Button type="button" variant="outline" onClick={handleCancel}>
                        Cancel
                    </Button>
                    <div className="flex gap-2">
                        <Button type="button" variant="outline" onClick={handleContinue}>
                            Continue current chat
                        </Button>
                        <Button type="button" onClick={handleStart}>
                            Start fresh
                        </Button>
                    </div>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
