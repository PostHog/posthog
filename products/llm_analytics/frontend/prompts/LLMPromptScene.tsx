import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'

import { IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { NotFound } from 'lib/components/NotFound'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { useTracesQueryContext } from '../LLMAnalyticsTracesScene'
import { PromptLogicProps, PromptMode, isPrompt, llmPromptLogic } from './llmPromptLogic'
import { openDeletePromptDialog } from './utils'

export const scene: SceneExport<PromptLogicProps> = {
    component: LLMPromptScene,
    logic: llmPromptLogic,
    productKey: ProductKey.LLM_ANALYTICS,
    paramsToProps: ({ params: { name }, searchParams }) => ({
        promptName: name && name !== 'new' ? name : 'new',
        mode: searchParams?.edit === 'true' ? PromptMode.Edit : PromptMode.View,
    }),
}

export function LLMPromptScene(): JSX.Element {
    const {
        shouldDisplaySkeleton,
        promptLoading,
        isPromptFormSubmitting,
        isPromptMissing,
        isNewPrompt,
        promptForm,
        isViewMode,
        prompt,
    } = useValues(llmPromptLogic)

    const { submitPromptForm, deletePrompt, setMode } = useActions(llmPromptLogic)

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

    if (isViewMode) {
        return (
            <SceneContent>
                <SceneTitleSection
                    name={prompt && 'name' in prompt ? prompt.name : 'Prompt'}
                    resourceType={{ type: 'llm_analytics' }}
                    isLoading={promptLoading}
                    actions={
                        <>
                            <AccessControlAction
                                resourceType={AccessControlResourceType.LlmAnalytics}
                                minAccessLevel={AccessControlLevel.Editor}
                            >
                                <LemonButton
                                    type="primary"
                                    icon={<IconPencil />}
                                    onClick={() => setMode(PromptMode.Edit)}
                                    size="small"
                                    data-attr="prompt-edit-button"
                                >
                                    Edit
                                </LemonButton>
                            </AccessControlAction>

                            <AccessControlAction
                                resourceType={AccessControlResourceType.LlmAnalytics}
                                minAccessLevel={AccessControlLevel.Editor}
                            >
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
                            </AccessControlAction>
                        </>
                    }
                />

                <PromptViewDetails />

                <PromptRelatedTraces />
            </SceneContent>
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
                                onClick={() => {
                                    if (isNewPrompt) {
                                        router.actions.push(urls.llmAnalyticsPrompts())
                                    } else {
                                        setMode(PromptMode.View)
                                    }
                                }}
                                disabledReason={isPromptFormSubmitting ? 'Saving…' : undefined}
                                size="small"
                                data-attr="prompt-cancel-button"
                            >
                                Cancel
                            </LemonButton>

                            <AccessControlAction
                                resourceType={AccessControlResourceType.LlmAnalytics}
                                minAccessLevel={AccessControlLevel.Editor}
                            >
                                <LemonButton
                                    type="primary"
                                    onClick={submitPromptForm}
                                    loading={isPromptFormSubmitting}
                                    size="small"
                                    data-attr={isNewPrompt ? 'prompt-create-button' : 'prompt-save-button'}
                                >
                                    {isNewPrompt ? 'Create prompt' : 'Save'}
                                </LemonButton>
                            </AccessControlAction>

                            {!isNewPrompt && (
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.LlmAnalytics}
                                    minAccessLevel={AccessControlLevel.Editor}
                                >
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
                                </AccessControlAction>
                            )}
                        </>
                    }
                />

                <PromptEditForm />
            </SceneContent>
        </Form>
    )
}

function PromptViewDetails(): JSX.Element {
    const { prompt } = useValues(llmPromptLogic)

    if (!prompt || !isPrompt(prompt)) {
        return <></>
    }

    const promptText = prompt.prompt
    const variableMatches = promptText.match(/\{\{([^}]+)\}\}/g)
    const variables = variableMatches ? [...new Set(variableMatches.map((m: string) => m.slice(2, -2).trim()))] : []

    return (
        <div className="space-y-4 max-w-3xl">
            <div>
                <label className="text-xs font-semibold text-secondary uppercase">Name</label>
                <p className="font-mono">{prompt.name}</p>
            </div>

            <div>
                <label className="text-xs font-semibold text-secondary uppercase">Prompt</label>
                <pre className="whitespace-pre-wrap bg-bg-light p-3 rounded border mt-1">{prompt.prompt}</pre>
            </div>

            {variables.length > 0 && (
                <div className="flex flex-wrap items-center gap-1">
                    <span className="text-xs text-secondary">Variables:</span>
                    {variables.map((v) => (
                        <LemonTag key={v} type="highlight" size="small">
                            {v}
                        </LemonTag>
                    ))}
                </div>
            )}
        </div>
    )
}

function PromptRelatedTraces(): JSX.Element {
    const { prompt, relatedTracesQuery, viewAllTracesUrl } = useValues(llmPromptLogic)
    const tracesQueryContext = useTracesQueryContext()

    if (!prompt || !isPrompt(prompt)) {
        return <></>
    }

    return (
        <div className="mt-8" data-attr="prompt-related-traces-section">
            <div className="flex items-center justify-between mb-4">
                <div>
                    <h3 className="text-lg font-semibold">Related traces</h3>
                    <p className="text-secondary text-sm mt-1">
                        To link traces to this prompt, set{' '}
                        <code className="bg-bg-light px-1 rounded">$ai_prompt_name</code> to{' '}
                        <code className="bg-bg-light px-1 rounded">{prompt.name}</code> when capturing LLM events.
                    </p>
                </div>

                <LemonButton
                    type="secondary"
                    to={viewAllTracesUrl}
                    size="small"
                    data-attr="prompt-view-all-traces-button"
                >
                    View all traces
                </LemonButton>
            </div>

            {relatedTracesQuery && (
                <DataTable
                    query={relatedTracesQuery}
                    setQuery={() => {}}
                    context={tracesQueryContext}
                    uniqueKey="prompt-related-traces"
                />
            )}
        </div>
    )
}

function PromptEditForm(): JSX.Element {
    const { promptVariables, isNewPrompt } = useValues(llmPromptLogic)

    return (
        <div className="space-y-4 max-w-3xl">
            <LemonField
                name="name"
                label="Name"
                help={
                    isNewPrompt
                        ? 'This name is used to fetch the prompt from your code. It must be unique and cannot be changed later. Only letters, numbers, hyphens (-), and underscores (_) are allowed.'
                        : 'This name is used to fetch the prompt from your code.'
                }
            >
                <LemonInput
                    placeholder="my-prompt-name"
                    fullWidth
                    disabledReason={!isNewPrompt ? 'Prompt name cannot be changed after creation' : undefined}
                />
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
