import { BindLogic, useActions, useValues } from 'kea'
import { type MutableRefObject, useRef } from 'react'

import { RunSurface } from 'products/posthog_ai/frontend/api/runSurface'

import { RunEscapeBoundary, type RunEscapeBoundaryProps } from '../../../components/RunEscapeBoundary'
import { runInteractionLogic, type RunInteractionLogicProps } from '../../../logics/runInteractionLogic'
import { taskTrackerSceneLogic } from '../taskTrackerSceneLogic'
import { TaskRunComposer } from './TaskRunComposer'

export function StartupRunChat({
    streamKey,
    focusedRef,
    escapeScope = 'composer',
}: {
    streamKey: string
    focusedRef?: MutableRefObject<boolean>
    escapeScope?: RunEscapeBoundaryProps['scope']
}): JSX.Element {
    const textAreaRef = useRef<HTMLTextAreaElement>(null)
    const flushDraftRef = useRef<() => void>(() => {})
    const { activeCreation } = useValues(taskTrackerSceneLogic)
    const logicProps: RunInteractionLogicProps = {
        taskId: activeCreation?.taskId ?? '',
        runId: activeCreation?.runId ?? '',
        streamKey,
        interactionKey: streamKey,
        flushDraft: () => flushDraftRef.current(),
    }
    const interaction = runInteractionLogic(logicProps)
    const { handleEscape } = useActions(interaction)
    const { cancellationState } = useValues(interaction)

    return (
        <BindLogic logic={runInteractionLogic} props={logicProps}>
            <RunSurface.Root taskId="" runId={null} streamKey={streamKey} interaction="live">
                <RunEscapeBoundary
                    scope={escapeScope}
                    focusKey={streamKey}
                    textAreaRef={textAreaRef}
                    onEscape={handleEscape}
                    className="@container/thread flex flex-col flex-1 h-full min-h-0 -mx-4"
                >
                    <RunSurface.Thread className="flex-1 min-h-0" listClassName="py-4" rowClassName="px-4" />
                    <RunSurface.Composer isStopping={!!cancellationState}>
                        <div
                            onFocusCapture={() => {
                                if (focusedRef) {
                                    focusedRef.current = true
                                }
                            }}
                            onBlurCapture={() => {
                                if (focusedRef) {
                                    focusedRef.current = false
                                }
                            }}
                        >
                            <TaskRunComposer
                                logicProps={interaction.props}
                                textAreaRef={textAreaRef}
                                flushDraftRef={flushDraftRef}
                                autoFocus
                            />
                        </div>
                    </RunSurface.Composer>
                </RunEscapeBoundary>
            </RunSurface.Root>
        </BindLogic>
    )
}
