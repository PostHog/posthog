import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { PromptLogicProps, llmPromptLogic } from './llmPromptLogic'
import { openDeletePromptDialog } from './utils'

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

    const { submitPromptForm, deletePrompt } = useActions(llmPromptLogic)

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
                                data-attr="prompt-cancel-button"
                            >
                                Cancel
                            </LemonButton>

                            {!isNewPrompt && (
                                <LemonButton
                                    type="secondary"
                                    status="danger"
                                    icon={<IconTrash />}
                                    onClick={() => openDeletePromptDialog(deletePrompt)}
                                    size="small"
                                    data-attr="prompt-delete-button"
                                >
                                    Delete
                                </LemonButton>
                            )}

                            <LemonButton
                                type="primary"
                                onClick={submitPromptForm}
                                loading={isPromptFormSubmitting}
                                size="small"
                                data-attr={isNewPrompt ? 'prompt-create-button' : 'prompt-save-button'}
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
    const { promptVariables } = useValues(llmPromptLogic)

    return (
        <div className="space-y-4 max-w-3xl">
            <LemonField
                name="name"
                label="Name"
                help="This name is used to fetch the prompt from your code. It must be unique. Only letters, numbers, hyphens (-), and underscores (_) are allowed."
            >
                <LemonInput placeholder="my-prompt-name" fullWidth />
            </LemonField>

            <LemonField
                name="prompt"
                label="Prompt"
                help="Use {{variable_name}} to define variables that will be replaced when fetching the prompt from your backend."
            >
                <LemonTextArea
                    placeholder="You are a helpful assistant for {{company_name}}. Help the user with their question about {{topic}}."
                    minRows={10}
                />
            </LemonField>

            {promptVariables.length > 0 && (
                <div className="flex flex-wrap items-center gap-1">
                    <span className="text-xs text-secondary">Variables to be replaced:</span>
                    {promptVariables.map((v: string) => (
                        <LemonTag key={v} type="highlight" size="small">
                            {v}
                        </LemonTag>
                    ))}
                </div>
            )}
        </div>
    )
}
