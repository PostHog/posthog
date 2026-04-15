import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconPlusSmall } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { LemonDialog } from '~/lib/lemon-ui/LemonDialog'
import { LemonField } from '~/lib/lemon-ui/LemonField'
import { LemonInput } from '~/lib/lemon-ui/LemonInput'
import { LemonTable, LemonTableColumn, LemonTableColumns } from '~/lib/lemon-ui/LemonTable'
import { atColumn } from '~/lib/lemon-ui/LemonTable/columnUtils'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, LLMPrompt } from '~/types'

import { PROMPTS_PER_PAGE, llmPromptsLogic } from './llmPromptsLogic'
import { openArchivePromptDialog } from './utils'

export const scene: SceneExport = {
    component: LLMPromptsScene,
    logic: llmPromptsLogic,
    productKey: ProductKey.LLM_ANALYTICS,
}

export function LLMPromptsScene(): JSX.Element {
    const { setFilters, deletePrompt, duplicatePrompt } = useActions(llmPromptsLogic)
    const { prompts, promptsLoading, sorting, pagination, filters, promptCountLabel } = useValues(llmPromptsLogic)
    const { searchParams } = useValues(router)
    const promptUrl = (name: string): string => combineUrl(urls.llmAnalyticsPrompt(name), searchParams).url

    const columns: LemonTableColumns<LLMPrompt> = [
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            width: '25%',
            render: function renderName(_, prompt) {
                return (
                    <Link to={promptUrl(prompt.name)} className="font-semibold" data-attr="llma-prompt-name-link">
                        {prompt.name}
                    </Link>
                )
            },
        },
        {
            title: 'Prompt',
            dataIndex: 'prompt',
            key: 'prompt',
            width: '40%',
            render: function renderPrompt(prompt) {
                const displayValue = typeof prompt === 'string' ? prompt : JSON.stringify(prompt)
                const truncated = displayValue.length > 100 ? displayValue.slice(0, 100) + '...' : displayValue

                return <span className="text-muted font-mono text-sm">{truncated || <i>–</i>}</span>
            },
        },
        {
            title: 'Latest author',
            dataIndex: 'created_by',
            render: function renderCreatedBy(_, item) {
                const { created_by } = item

                return (
                    <div className="flex flex-row items-center flex-nowrap">
                        {created_by && <ProfilePicture user={created_by} size="md" showName />}
                    </div>
                )
            },
        },
        {
            title: 'Versions',
            dataIndex: 'version_count',
            key: 'version_count',
            width: 100,
            render: function renderVersionCount(_, prompt) {
                return <span className="text-muted-alt">{prompt.version_count}</span>
            },
        },
        atColumn('created_at', 'Latest version created') as LemonTableColumn<LLMPrompt, keyof LLMPrompt | undefined>,
        {
            width: 0,
            render: function renderMore(_, prompt) {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    to={promptUrl(prompt.name)}
                                    data-attr="llma-prompt-dropdown-view"
                                    fullWidth
                                >
                                    View
                                </LemonButton>

                                <AccessControlAction
                                    resourceType={AccessControlResourceType.LlmAnalytics}
                                    minAccessLevel={AccessControlLevel.Editor}
                                >
                                    <LemonButton
                                        onClick={() => {
                                            LemonDialog.openForm({
                                                title: 'Duplicate prompt',
                                                initialValues: {
                                                    newName: `${prompt.name}-copy`,
                                                },
                                                content: (
                                                    <LemonField name="newName" label="New prompt name">
                                                        <LemonInput
                                                            data-attr="llma-prompt-duplicate-name"
                                                            placeholder="my-prompt-copy"
                                                            autoFocus
                                                        />
                                                    </LemonField>
                                                ),
                                                errors: {
                                                    newName: (name: string) =>
                                                        !name
                                                            ? 'You must enter a name'
                                                            : !/^[a-zA-Z0-9_-]+$/.test(name)
                                                              ? 'Only letters, numbers, hyphens, and underscores allowed'
                                                              : undefined,
                                                },
                                                onSubmit: async ({ newName }) => {
                                                    duplicatePrompt(prompt.name, newName)
                                                },
                                            })
                                        }}
                                        data-attr="llma-prompt-dropdown-duplicate"
                                        fullWidth
                                    >
                                        Duplicate
                                    </LemonButton>
                                </AccessControlAction>

                                <AccessControlAction
                                    resourceType={AccessControlResourceType.LlmAnalytics}
                                    minAccessLevel={AccessControlLevel.Editor}
                                >
                                    <LemonButton
                                        status="danger"
                                        onClick={() => openArchivePromptDialog(() => deletePrompt(prompt.name))}
                                        data-attr="llma-prompt-dropdown-delete"
                                        fullWidth
                                    >
                                        Archive
                                    </LemonButton>
                                </AccessControlAction>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name="Prompts"
                description="Track and manage your LLM prompts."
                resourceType={{ type: 'llm_prompts' }}
                actions={
                    <AccessControlAction
                        resourceType={AccessControlResourceType.LlmAnalytics}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            type="primary"
                            to={promptUrl('new')}
                            icon={<IconPlusSmall />}
                            data-attr="new-prompt-button"
                        >
                            New prompt
                        </LemonButton>
                    </AccessControlAction>
                }
            />

            <div className="space-y-4">
                <div className="flex gap-x-4 gap-y-2 items-center flex-wrap">
                    <LemonInput
                        type="search"
                        placeholder="Search prompts..."
                        value={filters.search}
                        data-attr="prompts-search-input"
                        onChange={(value) => setFilters({ search: value })}
                        className="max-w-md"
                    />
                    <div className="text-muted-alt">{promptCountLabel}</div>
                </div>

                <LemonTable
                    loading={promptsLoading}
                    columns={columns}
                    dataSource={prompts.results}
                    pagination={pagination}
                    noSortingCancellation
                    sorting={sorting}
                    onSort={(newSorting) =>
                        setFilters({
                            order_by: newSorting
                                ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}`
                                : undefined,
                        })
                    }
                    rowKey="id"
                    loadingSkeletonRows={PROMPTS_PER_PAGE}
                    nouns={['prompt', 'prompts']}
                />
            </div>
        </SceneContent>
    )
}
