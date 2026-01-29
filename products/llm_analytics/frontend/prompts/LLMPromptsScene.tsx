import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { LemonInput } from '~/lib/lemon-ui/LemonInput'
import { LemonTable, LemonTableColumn, LemonTableColumns } from '~/lib/lemon-ui/LemonTable'
import { createdAtColumn } from '~/lib/lemon-ui/LemonTable/columnUtils'
import { LLMPrompt } from '~/types'

import { PROMPTS_PER_PAGE, llmPromptsLogic } from './llmPromptsLogic'
import { openDeletePromptDialog } from './utils'

export const scene: SceneExport = {
    component: LLMPromptsScene,
    logic: llmPromptsLogic,
}

export function LLMPromptsScene(): JSX.Element {
    const { setFilters, deletePrompt } = useActions(llmPromptsLogic)
    const { prompts, promptsLoading, sorting, pagination, filters, promptCountLabel } = useValues(llmPromptsLogic)

    const columns: LemonTableColumns<LLMPrompt> = [
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            width: '25%',
            render: function renderName(_, prompt) {
                return (
                    <Link
                        to={urls.llmAnalyticsPrompt(prompt.id)}
                        className="font-semibold"
                        data-attr="prompt-name-link"
                    >
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
            title: 'Created by',
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
        createdAtColumn<LLMPrompt>() as LemonTableColumn<LLMPrompt, keyof LLMPrompt | undefined>,
        {
            width: 0,
            render: function renderMore(_, prompt) {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    to={urls.llmAnalyticsPrompt(prompt.id)}
                                    data-attr="prompt-dropdown-view"
                                    fullWidth
                                >
                                    View
                                </LemonButton>

                                <LemonButton
                                    status="danger"
                                    onClick={() => openDeletePromptDialog(() => deletePrompt(prompt.id))}
                                    data-attr="prompt-dropdown-delete"
                                    fullWidth
                                >
                                    Delete
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <div className="space-y-4">
            <div className="flex gap-x-4 gap-y-2 items-center flex-wrap justify-between">
                <div className="flex gap-x-4 items-center">
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

                <LemonButton
                    type="primary"
                    to={urls.llmAnalyticsPrompt('new')}
                    icon={<IconPlusSmall />}
                    data-attr="new-prompt-button"
                >
                    New prompt
                </LemonButton>
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
    )
}
