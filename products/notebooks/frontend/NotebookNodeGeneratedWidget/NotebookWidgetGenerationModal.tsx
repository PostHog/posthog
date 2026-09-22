import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import {
    type NotebookNodeGeneratedWidgetLogicProps,
    notebookNodeGeneratedWidgetLogic,
} from './notebookNodeGeneratedWidgetLogic'
import { MAX_WIDGET_EFFECTIVE_PROMPT_LENGTH, MAX_WIDGET_PROMPT_LENGTH, WIDGET_MODEL_OPTIONS } from './widgetModels'

export function NotebookWidgetGenerationModal({
    logicProps,
}: {
    logicProps: NotebookNodeGeneratedWidgetLogicProps
}): JSX.Element {
    const logic = notebookNodeGeneratedWidgetLogic(logicProps)
    const {
        generationDraftModel,
        generationDraftPrompt,
        generationError,
        generationModalOperation,
        generationRequestLoading,
        isWorking,
        selectedVersion,
    } = useValues(logic)
    const { closeGenerationModal, generateWidget, setGenerationDraftModel, setGenerationDraftPrompt } =
        useActions(logic)
    const promptId = `widget-change-prompt-${logicProps.nodeId}`
    const modelId = `widget-change-model-${logicProps.nodeId}`
    const isRegenerationVersionLoading = generationModalOperation === 'regenerate' && !selectedVersion
    const isImprovementVersionLoading = generationModalOperation === 'improve' && !selectedVersion
    const modalTitle = generationModalOperation === 'improve' ? 'Improve widget' : 'Regenerate widget'
    const modalDescription =
        generationModalOperation === 'improve'
            ? 'Describe one change. The generator will use the current widget as a starting point and create a new version.'
            : 'Edit the complete instructions below. This creates a new version from scratch and keeps existing versions.'
    const submitGenerationDraft = (prompt: string): void => {
        if (
            !generationModalOperation ||
            !prompt.trim() ||
            generationRequestLoading ||
            isWorking ||
            isRegenerationVersionLoading ||
            isImprovementVersionLoading
        ) {
            return
        }
        generateWidget(prompt, generationDraftModel, generationModalOperation, selectedVersion?.id)
    }

    return (
        <LemonModal
            isOpen={generationModalOperation !== null}
            onClose={closeGenerationModal}
            title={modalTitle}
            description={modalDescription}
            width={640}
            footer={
                <>
                    <LemonButton onClick={closeGenerationModal}>Cancel</LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => submitGenerationDraft(generationDraftPrompt)}
                        disabledReason={
                            isRegenerationVersionLoading || isImprovementVersionLoading
                                ? 'Loading the widget version.'
                                : !generationDraftPrompt.trim()
                                  ? 'Add instructions first'
                                  : undefined
                        }
                        loading={generationRequestLoading}
                    >
                        {generationModalOperation === 'improve' ? 'Improve' : 'Regenerate'}
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <div>
                    <LemonLabel htmlFor={promptId}>
                        {generationModalOperation === 'improve' ? 'Change to make' : 'Full instructions'}
                    </LemonLabel>
                    <LemonTextArea
                        id={promptId}
                        value={generationDraftPrompt}
                        onChange={setGenerationDraftPrompt}
                        onPressCmdEnter={submitGenerationDraft}
                        minRows={6}
                        autoFocus
                        disabled={isRegenerationVersionLoading || isImprovementVersionLoading}
                        maxLength={
                            generationModalOperation === 'regenerate'
                                ? MAX_WIDGET_EFFECTIVE_PROMPT_LENGTH
                                : MAX_WIDGET_PROMPT_LENGTH
                        }
                        className="mt-1 ph-no-capture"
                        placeholder={
                            generationModalOperation === 'improve'
                                ? 'For example, make the colors lighter and increase the label contrast.'
                                : 'Describe the complete widget.'
                        }
                    />
                </div>
                <div>
                    <LemonLabel htmlFor={modelId}>Model</LemonLabel>
                    <LemonSelect
                        id={modelId}
                        value={generationDraftModel}
                        options={WIDGET_MODEL_OPTIONS}
                        onChange={setGenerationDraftModel}
                        disabled={isRegenerationVersionLoading || isImprovementVersionLoading}
                        fullWidth
                        className="mt-1"
                    />
                </div>
                {generationError ? <LemonBanner type="error">{generationError}</LemonBanner> : null}
            </div>
        </LemonModal>
    )
}
