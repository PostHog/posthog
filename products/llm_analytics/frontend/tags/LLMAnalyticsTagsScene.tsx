import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconPencil, IconPlus, IconSearch, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSwitch, LemonTable, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { TrialUsageMeter } from '../settings/TrialUsageMeter'
import { llmTaggersLogic } from './llmTaggersLogic'
import { Tagger } from './types'

export const scene: SceneExport = {
    component: LLMAnalyticsTagsScene,
    logic: llmTaggersLogic,
    productKey: ProductKey.LLM_ANALYTICS,
}

function LLMAnalyticsTagsContent({ tabId }: { tabId?: string }): JSX.Element {
    const taggersLogic = llmTaggersLogic({ tabId })
    const { filteredTaggers, taggersLoading, taggersFilter } = useValues(taggersLogic)
    const { setTaggersFilter, toggleTaggerEnabled, loadTaggers } = useActions(taggersLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { push } = useActions(router)
    const { searchParams } = useValues(router)
    const taggerUrl = (id: string): string => combineUrl(urls.llmAnalyticsTag(id), searchParams).url

    const columns: LemonTableColumns<Tagger> = [
        {
            title: 'Name',
            key: 'name',
            render: (_, tagger) => (
                <div className="flex flex-col">
                    <Link to={taggerUrl(tagger.id)} className="font-semibold text-primary">
                        {tagger.name}
                    </Link>
                    {tagger.description && <div className="text-muted text-sm">{tagger.description}</div>}
                </div>
            ),
            sorter: (a, b) => a.name.localeCompare(b.name),
        },
        {
            title: 'Status',
            key: 'enabled',
            render: (_, tagger) => (
                <div className="flex items-center gap-2">
                    <AccessControlAction
                        resourceType={AccessControlResourceType.LlmAnalytics}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonSwitch
                            checked={tagger.enabled}
                            onChange={() => toggleTaggerEnabled(tagger.id)}
                            size="small"
                            data-attr="toggle-tagger-enabled"
                        />
                    </AccessControlAction>
                    <span className={tagger.enabled ? 'text-success' : 'text-muted'}>
                        {tagger.enabled ? 'Enabled' : 'Disabled'}
                    </span>
                </div>
            ),
            sorter: (a, b) => Number(b.enabled) - Number(a.enabled),
        },
        {
            title: 'Tags',
            key: 'tags',
            render: (_, tagger) => (
                <div className="flex flex-wrap gap-1">
                    {tagger.tagger_config.tags.slice(0, 5).map((tag) => (
                        <LemonTag key={tag.name} type="option">
                            {tag.name}
                        </LemonTag>
                    ))}
                    {tagger.tagger_config.tags.length > 5 && (
                        <LemonTag type="muted">+{tagger.tagger_config.tags.length - 5}</LemonTag>
                    )}
                </div>
            ),
        },
        {
            title: 'Prompt',
            key: 'prompt',
            render: (_, tagger) => (
                <Tooltip title={tagger.tagger_config.prompt} placement="top">
                    <div className="max-w-md">
                        <div className="text-sm font-mono bg-bg-light border rounded px-2 py-1 truncate cursor-default">
                            {tagger.tagger_config.prompt || '(empty)'}
                        </div>
                    </div>
                </Tooltip>
            ),
        },
        {
            title: 'Triggers',
            key: 'conditions',
            render: (_, tagger) => (
                <div className="flex flex-wrap gap-1">
                    {tagger.conditions.map((condition) => (
                        <LemonTag key={condition.id} type="option">
                            {parseFloat(condition.rollout_percentage.toFixed(2))}%
                            {condition.properties.length > 0 &&
                                ` when ${condition.properties.length} condition${condition.properties.length !== 1 ? 's' : ''}`}
                        </LemonTag>
                    ))}
                    {tagger.conditions.length === 0 && <span className="text-muted text-sm">No triggers</span>}
                </div>
            ),
        },
        {
            title: 'Actions',
            key: 'actions',
            render: (_, tagger) => (
                <div className="flex gap-1">
                    <AccessControlAction
                        resourceType={AccessControlResourceType.LlmAnalytics}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconPencil />}
                            onClick={() => push(taggerUrl(tagger.id))}
                        />
                    </AccessControlAction>
                    <AccessControlAction
                        resourceType={AccessControlResourceType.LlmAnalytics}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            size="small"
                            type="secondary"
                            status="danger"
                            icon={<IconTrash />}
                            onClick={() => {
                                deleteWithUndo({
                                    endpoint: `environments/${currentTeamId}/taggers`,
                                    object: tagger,
                                    callback: () => loadTaggers(),
                                })
                            }}
                        />
                    </AccessControlAction>
                </div>
            ),
        },
    ]

    return (
        <div className="space-y-4">
            <TrialUsageMeter showSettingsLink={false} />

            <div className="flex justify-between items-center">
                <div>
                    <h2 className="text-xl font-semibold">Tags</h2>
                    <p className="text-muted">
                        Set up taggers to automatically add custom tags to your LLM generations.
                    </p>
                </div>
                <AccessControlAction
                    resourceType={AccessControlResourceType.LlmAnalytics}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        to={combineUrl(urls.llmAnalyticsTag('new'), searchParams).url}
                        data-attr="create-tagger-button"
                    >
                        Create tagger
                    </LemonButton>
                </AccessControlAction>
            </div>

            <div className="flex items-center gap-2">
                <LemonInput
                    type="search"
                    placeholder="Search taggers..."
                    value={taggersFilter}
                    data-attr="taggers-search-input"
                    onChange={setTaggersFilter}
                    prefix={<IconSearch />}
                    className="max-w-sm"
                />
            </div>

            <LemonTable
                columns={columns}
                dataSource={filteredTaggers}
                loading={taggersLoading}
                rowKey="id"
                pagination={{
                    pageSize: 50,
                }}
                nouns={['tagger', 'taggers']}
                emptyState={<div />}
            />
        </div>
    )
}

export function LLMAnalyticsTagsScene({ tabId }: { tabId?: string }): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name="Tags"
                description="Automatically add custom tags to your LLM generations."
                resourceType={{
                    type: 'llm_taggers',
                }}
            />
            <LLMAnalyticsTagsContent tabId={tabId} />
        </SceneContent>
    )
}
