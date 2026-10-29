import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { tileCanvasLogic } from './tileCanvasLogic'

/** Laying out the same steps fails the same way again, so the way out is an earlier version. */
export function TileCanvasLayoutError({ message }: { message: string }): JSX.Element {
    const { hasUnsavedChanges, isSavedWorkflow } = useValues(tileCanvasLogic)
    const { discardChanges, openPanel } = useActions(tileCanvasLogic)
    return (
        <div
            className="absolute inset-0 z-10 flex items-center justify-center p-6"
            data-attr="workflow-tile-layout-error"
        >
            <div className="flex max-w-120 flex-col gap-3 rounded-lg border bg-surface-primary p-5 shadow">
                <h3 className="m-0 text-base font-semibold">The canvas couldn't draw this workflow</h3>
                <p className="m-0 text-sm text-secondary">
                    Laying out its steps failed, and it fails the same way each time.{' '}
                    {hasUnsavedChanges
                        ? 'Your unsaved changes are still here. Discard them to go back to the saved workflow.'
                        : 'Your saved workflow did not change. Open its history to go back to an earlier version.'}
                </p>
                <code className="block break-words rounded bg-surface-secondary px-2 py-1 text-xs">{message}</code>
                <div className="flex flex-wrap justify-end gap-2">
                    {hasUnsavedChanges ? (
                        <LemonButton type="primary" onClick={discardChanges}>
                            Discard changes
                        </LemonButton>
                    ) : (
                        isSavedWorkflow && (
                            <LemonButton type="primary" onClick={() => openPanel('history')}>
                                Open history
                            </LemonButton>
                        )
                    )}
                </div>
            </div>
        </div>
    )
}
