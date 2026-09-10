import { useActions, useValues } from 'kea'
import { type MutableRefObject, useRef } from 'react'

import { Composer } from 'products/posthog_ai/frontend/api/primitives'
import { RunSurface } from 'products/posthog_ai/frontend/api/runSurface'

import { RunEscapeBoundary } from '../../../components/RunEscapeBoundary'
import { runCancellationLogic } from '../../../logics/runCancellationLogic'
import { taskTrackerSceneLogic } from '../taskTrackerSceneLogic'

export function StartupRunChat({
    streamKey,
    focusedRef,
}: {
    streamKey: string
    focusedRef: MutableRefObject<boolean>
}): JSX.Element {
    const textAreaRef = useRef<HTMLTextAreaElement>(null)
    const { activeCreation } = useValues(taskTrackerSceneLogic)
    const { setStartupDraft } = useActions(taskTrackerSceneLogic)
    const { requestCancellation } = useActions(runCancellationLogic({ streamKey }))
    const { cancellationState } = useValues(runCancellationLogic({ streamKey }))

    return (
        <RunEscapeBoundary
            scope="composer"
            focusKey={streamKey}
            textAreaRef={textAreaRef}
            onEscape={requestCancellation}
            className="@container/thread flex flex-col flex-1 min-h-0"
        >
            <RunSurface.Root taskId="" runId={null} streamKey={streamKey} interaction="live">
                <RunSurface.Thread className="flex-1 min-h-0" listClassName="py-4" rowClassName="px-4" />
            </RunSurface.Root>
            <div
                className="px-4 pb-4"
                onFocusCapture={() => {
                    focusedRef.current = true
                }}
                onBlurCapture={() => {
                    focusedRef.current = false
                }}
            >
                <Composer.Root
                    textAreaRef={textAreaRef}
                    value={activeCreation?.draft ?? ''}
                    onChange={setStartupDraft}
                    onSubmit={() => {}}
                    disabledReason="Wait for the run to start"
                    stopLoading={!!cancellationState}
                    isTurnActive
                    onStop={requestCancellation}
                >
                    <Composer.Frame>
                        <Composer.Field>
                            <Composer.Placeholder>Send a follow-up message…</Composer.Placeholder>
                            <Composer.Textarea data-attr="sandbox-composer-input" autoFocus />
                        </Composer.Field>
                    </Composer.Frame>
                    <Composer.Submit data-attr="sandbox-composer-send" />
                </Composer.Root>
            </div>
        </RunEscapeBoundary>
    )
}
