import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { LLMPrompt } from '~/types'

import { PromptLogicProps, isPrompt, llmPromptLogic } from './llmPromptLogic'

export const scene: SceneExport<PromptLogicProps> = {
    component: LLMPromptScene,
    logic: llmPromptLogic,
    paramsToProps: ({ params: { id } }) => ({
        promptId: id && id !== 'new' ? id : 'new',
    }),
}

export function LLMPromptScene(): JSX.Element {
    const {
        shouldDisplaySkeleton,
        promptLoading,
        isPromptFormSubmitting,
        isEditingPrompt,
        isPromptMissing,
        isNewPrompt,
        promptForm,
        prompt,
    } = useValues(llmPromptLogic)

    const { submitPromptForm, loadPrompt, editPrompt, deletePrompt, onUnmount } = useActions(llmPromptLogic)

    const displayEditForm = isNewPrompt || isEditingPrompt

    useEffect(() => {
        return () => onUnmount()
    }, [onUnmount])

    if (isPromptMissing) {
        return <NotFound object="prompt" />
    }

    if (shouldDisplaySkeleton) {
        return (
            <div className="flex flex-col gap-2">
                <LemonSkeleton active className="h-4 w-2/5" />
                <LemonSkeleton active className="h-4 w-full" />
                <LemonSkeleton active className="h-4 w-3/5" />
            </div>
        )
    }

    return (
        <Form id="prompt-form" formKey="promptForm" logic={llmPromptLogic}>
            <SceneContent>
                <SceneTitleSection
                    name={promptForm.name || 'New prompt'}
                    resourceType={{ type: 'llm_analytics' }}
                    isLoading={promptLoading}
                    actions={
                        <>
                            {displayEditForm ? (
                                <>
                                    <LemonButton
                                        type="secondary"
                                        onClick={() => {
                                            if (isEditingPrompt) {
                                                editPrompt(false)
                                                loadPrompt()
                                            } else {
                                                router.actions.push(urls.llmAnalyticsPrompts())
                                            }
                                        }}
                                        disabledReason={isPromptFormSubmitting ? 'Saving…' : undefined}
                                        size="small"
                                    >
                                        Cancel
                                    </LemonButton>

                                    <LemonButton
                                        type="primary"
                                        onClick={submitPromptForm}
                                        loading={isPromptFormSubmitting}
                                        size="small"
                                    >
                                        {isNewPrompt ? 'Create prompt' : 'Save'}
                                    </LemonButton>
                                </>
                            ) : (
                                <>
                                    <LemonButton type="secondary" onClick={() => editPrompt(true)} size="small">
                                        Edit
                                    </LemonButton>

                                    <LemonButton
                                        type="secondary"
                                        status="danger"
                                        icon={<IconTrash />}
                                        onClick={() => {
                                            LemonDialog.open({
                                                title: 'Delete prompt?',
                                                description: 'This action cannot be undone.',
                                                primaryButton: {
                                                    children: 'Delete',
                                                    type: 'primary',
                                                    status: 'danger',
                                                    onClick: deletePrompt,
                                                },
                                                secondaryButton: {
                                                    children: 'Cancel',
                                                    type: 'secondary',
                                                },
                                            })
                                        }}
                                        size="small"
                                    >
                                        Delete
                                    </LemonButton>
                                </>
                            )}
                        </>
                    }
                />

                {displayEditForm ? <PromptEditForm /> : isPrompt(prompt) ? <PromptView prompt={prompt} /> : null}
            </SceneContent>
        </Form>
    )
}

function PromptEditForm(): JSX.Element {
    const { promptForm } = useValues(llmPromptLogic)
    const { setPromptFormValue } = useActions(llmPromptLogic)

    return (
        <div className="space-y-4 max-w-3xl">
            <div>
                <label className="font-semibold block mb-1">Name</label>
                <LemonInput
                    value={promptForm.name}
                    onChange={(value) => setPromptFormValue('name', value)}
                    placeholder="Enter prompt name"
                    fullWidth
                />
            </div>

            <div>
                <label className="font-semibold block mb-1">Prompt</label>
                <LemonTextArea
                    value={promptForm.prompt}
                    onChange={(value) => setPromptFormValue('prompt', value)}
                    placeholder="Enter your prompt content..."
                    minRows={10}
                />
            </div>
        </div>
    )
}

function PromptView({ prompt }: { prompt: LLMPrompt }): JSX.Element {
    return (
        <div className="space-y-4 max-w-3xl">
            <div>
                <h3 className="font-semibold text-sm mb-1">Prompt content</h3>
                <div className="bg-bg-light p-4 rounded border font-mono text-sm whitespace-pre-wrap">
                    {typeof prompt.prompt === 'string' ? prompt.prompt : JSON.stringify(prompt.prompt, null, 2)}
                </div>
            </div>

            <div className="text-muted text-sm">Version: v{prompt.version}</div>
        </div>
    )
}
