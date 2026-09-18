import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'

import {
    type NotebookNodeGeneratedWidgetLogicProps,
    notebookNodeGeneratedWidgetLogic,
} from './notebookNodeGeneratedWidgetLogic'
import { MAX_WIDGET_PROMPT_LENGTH } from './widgetModels'

export function NotebookWidgetSourceModal(props: NotebookNodeGeneratedWidgetLogicProps): JSX.Element {
    const logic = notebookNodeGeneratedWidgetLogic(props)
    const {
        generationError,
        generationRequestLoading,
        source,
        sourceChangePrompt,
        sourceError,
        sourceImprovementDisabledReason,
        sourceLoading,
        sourceModalOpen,
    } = useValues(logic)
    const { closeSourceModal, improveSource, loadSource, setSourceChangePrompt } = useActions(logic)
    const promptId = `widget-source-change-${props.nodeId}`

    return (
        <LemonModal
            isOpen={sourceModalOpen}
            onClose={closeSourceModal}
            title="Widget source"
            width="70vw"
            footer={
                props.isEditable ? (
                    <>
                        <LemonButton onClick={closeSourceModal}>Cancel</LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={improveSource}
                            disabledReason={sourceImprovementDisabledReason ?? undefined}
                            loading={generationRequestLoading}
                            data-attr="notebook-widget-build-source-changes"
                        >
                            Build changes
                        </LemonButton>
                    </>
                ) : (
                    <LemonButton onClick={closeSourceModal}>Close</LemonButton>
                )
            }
        >
            <div className="flex flex-col gap-4">
                <div>
                    <LemonLabel>Source</LemonLabel>
                    {sourceLoading ? (
                        <LemonSkeleton className="mt-1 h-80 w-full" />
                    ) : sourceError ? (
                        <LemonBanner
                            type="error"
                            className="mt-1"
                            action={{ children: 'Try again', onClick: loadSource }}
                        >
                            {sourceError}
                        </LemonBanner>
                    ) : source !== null ? (
                        <CodeEditorResizeable
                            className="mt-1 ph-no-capture"
                            language="typescript"
                            value={source}
                            minHeight="20rem"
                            maxHeight="50vh"
                            allowManualResize={false}
                            options={{ readOnly: true, minimap: { enabled: false } }}
                        />
                    ) : null}
                </div>
                {props.isEditable ? (
                    <div>
                        <LemonLabel htmlFor={promptId}>What would you like to change?</LemonLabel>
                        <LemonTextArea
                            id={promptId}
                            value={sourceChangePrompt}
                            onChange={setSourceChangePrompt}
                            onPressCmdEnter={improveSource}
                            placeholder="Describe the changes you want."
                            minRows={4}
                            maxLength={MAX_WIDGET_PROMPT_LENGTH}
                            autoFocus
                            className="mt-1 ph-no-capture"
                        />
                    </div>
                ) : null}
                {props.isEditable && generationError ? <LemonBanner type="error">{generationError}</LemonBanner> : null}
            </div>
        </LemonModal>
    )
}
