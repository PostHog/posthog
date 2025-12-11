import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { PromptLogicProps, llmPromptLogic } from './llmPromptLogic'

export const scene: SceneExport<PromptLogicProps> = {
    component: LLMPromptScene,
    logic: llmPromptLogic,
    paramsToProps: ({ params: { id } }) => ({
        promptId: id && id !== 'new' ? id : 'new',
    }),
}

export function LLMPromptScene(): JSX.Element {
    const { shouldDisplaySkeleton, promptLoading, isPromptFormSubmitting, isPromptMissing, isNewPrompt, promptForm } =
        useValues(llmPromptLogic)

    const { submitPromptForm, deletePrompt, onUnmount } = useActions(llmPromptLogic)

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
                            <LemonButton
                                type="secondary"
                                onClick={() => router.actions.push(urls.llmAnalyticsPrompts())}
                                disabledReason={isPromptFormSubmitting ? 'Saving…' : undefined}
                                size="small"
                            >
                                Cancel
                            </LemonButton>

                            {!isNewPrompt && (
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
                            )}

                            <LemonButton
                                type="primary"
                                onClick={submitPromptForm}
                                loading={isPromptFormSubmitting}
                                size="small"
                            >
                                {isNewPrompt ? 'Create prompt' : 'Save'}
                            </LemonButton>
                        </>
                    }
                />

                <PromptEditForm />
            </SceneContent>
        </Form>
    )
}

function PromptEditForm(): JSX.Element {
    const { promptForm, promptFormErrors, promptVariables } = useValues(llmPromptLogic)
    const { setPromptFormValue } = useActions(llmPromptLogic)

    return (
        <div className="space-y-4 max-w-3xl">
            <LemonField.Pure
                label="Name"
                help="This name is used to fetch the prompt from your code. It must be unique. Only letters, numbers, hyphens (-), and underscores (_) are allowed."
                error={promptFormErrors?.name}
            >
                <LemonInput
                    value={promptForm.name}
                    onChange={(value) => setPromptFormValue('name', value)}
                    placeholder="my-prompt-name"
                    fullWidth
                />
            </LemonField.Pure>

            <LemonField.Pure
                label="Prompt"
                help="Use {{variable_name}} to define variables that will be replaced when fetching the prompt from your backend."
                error={promptFormErrors?.prompt}
            >
                <LemonTextArea
                    value={promptForm.prompt}
                    onChange={(value) => setPromptFormValue('prompt', value)}
                    placeholder="You are a helpful assistant for {{company_name}}. Help the user with their question about {{topic}}."
                    minRows={10}
                />

                {promptVariables.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1 mt-2">
                        <span className="text-xs text-secondary">Variables to be replaced:</span>
                        {promptVariables.map((v: string) => (
                            <LemonTag key={v} type="highlight" size="small">
                                {v}
                            </LemonTag>
                        ))}
                    </div>
                )}
            </LemonField.Pure>
        </div>
    )
}
