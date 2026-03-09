import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { combineUrl, router } from 'kea-router'

import { IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, LemonTabs } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { NotFound } from 'lib/components/NotFound'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { PromptLogicProps, PromptMode, isPrompt, llmPromptLogic } from './llmPromptLogic'
import {
    PromptEditForm,
    PromptRelatedTraces,
    PromptUsage,
    PromptVersionSidebar,
    PromptViewDetails,
    cleanPromptSearchParams,
} from './promptSceneComponents'
import { openArchivePromptDialog } from './utils'

export const scene: SceneExport<PromptLogicProps> = {
    component: LLMPromptScene,
    logic: llmPromptLogic,
    productKey: ProductKey.LLM_ANALYTICS,
    paramsToProps: ({ params: { name }, searchParams }) => ({
        promptName: name && name !== 'new' ? name : 'new',
        mode: searchParams?.edit === 'true' ? PromptMode.Edit : PromptMode.View,
        selectedVersion: searchParams?.version ? Number(searchParams.version) || null : null,
    }),
}

export function LLMPromptScene(): JSX.Element {
    const {
        shouldDisplaySkeleton,
        promptLoading,
        versionsLoading,
        isPromptFormSubmitting,
        isPromptMissing,
        isNewPrompt,
        promptForm,
        isViewMode,
        prompt,
        isHistoricalVersion,
        versions,
        canLoadMoreVersions,
    } = useValues(llmPromptLogic)
    const { searchParams } = useValues(router)
    const currentSearchParams = searchParams ?? {}
    const activeViewTab = searchParams?.tab === 'usage' ? 'usage' : 'overview'

    const { submitPromptForm, deletePrompt, setMode, setPromptFormValues, loadMoreVersions } =
        useActions(llmPromptLogic)

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

    const content = isViewMode ? (
        <SceneContent>
            <SceneTitleSection
                name={prompt && 'name' in prompt ? prompt.name : 'Prompt'}
                resourceType={{ type: 'llm_analytics' }}
                isLoading={promptLoading}
                actions={
                    <>
                        {isPrompt(prompt) && prompt.is_latest ? (
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
                                    Edit latest
                                </LemonButton>
                            </AccessControlAction>
                        ) : (
                            <AccessControlAction
                                resourceType={AccessControlResourceType.LlmAnalytics}
                                minAccessLevel={AccessControlLevel.Editor}
                            >
                                <LemonButton
                                    type="primary"
                                    onClick={() => {
                                        if (isPrompt(prompt)) {
                                            setPromptFormValues({ name: prompt.name, prompt: prompt.prompt })
                                            setMode(PromptMode.Edit)
                                        }
                                    }}
                                    size="small"
                                    data-attr="prompt-use-as-latest-button"
                                >
                                    Use as latest
                                </LemonButton>
                            </AccessControlAction>
                        )}

                        <AccessControlAction
                            resourceType={AccessControlResourceType.LlmAnalytics}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonButton
                                type="secondary"
                                status="danger"
                                icon={<IconTrash />}
                                onClick={() => openArchivePromptDialog(deletePrompt)}
                                size="small"
                                data-attr="prompt-delete-button"
                            >
                                Archive
                            </LemonButton>
                        </AccessControlAction>
                    </>
                }
            />

            <div className="flex flex-col gap-6 xl:flex-row">
                <div className="min-w-0 flex-1">
                    {prompt && isPrompt(prompt) ? (
                        <LemonTabs
                            activeKey={activeViewTab}
                            onChange={(tab) =>
                                router.actions.replace(urls.llmAnalyticsPrompt(prompt.name), {
                                    ...cleanPromptSearchParams(
                                        currentSearchParams,
                                        prompt.is_latest ? null : prompt.version
                                    ),
                                    tab,
                                })
                            }
                            tabs={[
                                {
                                    key: 'overview',
                                    label: 'Overview',
                                    content: (
                                        <>
                                            <PromptViewDetails />
                                            <PromptRelatedTraces />
                                        </>
                                    ),
                                },
                                {
                                    key: 'usage',
                                    label: 'Usage',
                                    content: <PromptUsage prompt={prompt} />,
                                },
                            ]}
                        />
                    ) : (
                        <>
                            <PromptViewDetails />
                            <PromptRelatedTraces />
                        </>
                    )}
                </div>

                {!isNewPrompt && (
                    <PromptVersionSidebar
                        promptName={isPrompt(prompt) ? prompt.name : ''}
                        prompt={isPrompt(prompt) ? prompt : null}
                        versions={versions}
                        versionsLoading={versionsLoading}
                        canLoadMoreVersions={canLoadMoreVersions}
                        loadMoreVersions={loadMoreVersions}
                        searchParams={currentSearchParams}
                    />
                )}
            </div>
        </SceneContent>
    ) : (
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
                                        router.actions.push(
                                            combineUrl(urls.llmAnalyticsPrompts(), currentSearchParams).url
                                        )
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
                                    {isNewPrompt ? 'Create prompt' : 'Publish version'}
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
                                        onClick={() => openArchivePromptDialog(deletePrompt)}
                                        size="small"
                                        data-attr="prompt-delete-button"
                                    >
                                        Archive
                                    </LemonButton>
                                </AccessControlAction>
                            )}
                        </>
                    }
                />

                <div className="flex flex-col gap-6 xl:flex-row">
                    <div className="min-w-0 flex-1">
                        <PromptEditForm
                            isHistoricalVersion={isHistoricalVersion}
                            selectedVersion={isPrompt(prompt) ? prompt.version : null}
                        />
                    </div>

                    {!isNewPrompt && (
                        <PromptVersionSidebar
                            promptName={isPrompt(prompt) ? prompt.name : ''}
                            prompt={isPrompt(prompt) ? prompt : null}
                            versions={versions}
                            versionsLoading={versionsLoading}
                            canLoadMoreVersions={canLoadMoreVersions}
                            loadMoreVersions={loadMoreVersions}
                            searchParams={currentSearchParams}
                        />
                    )}
                </div>
            </SceneContent>
        </Form>
    )
    return content
}
