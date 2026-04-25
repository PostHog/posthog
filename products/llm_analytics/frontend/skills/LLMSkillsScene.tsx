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
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { LLMSkillListApi } from '../generated/api.schemas'
import { SKILLS_PER_PAGE, llmSkillsLogic } from './llmSkillsLogic'
import { SKILL_NAME_MAX_LENGTH, validateSkillName } from './skillConstants'
import { openArchiveSkillDialog } from './skillSceneComponents'

export const scene: SceneExport = {
    component: LLMSkillsScene,
    logic: llmSkillsLogic,
    productKey: ProductKey.LLM_ANALYTICS,
}

export function LLMSkillsScene(): JSX.Element {
    const { setFilters, deleteSkill, duplicateSkill } = useActions(llmSkillsLogic)
    const { skills, skillsLoading, sorting, pagination, filters, skillCountLabel } = useValues(llmSkillsLogic)
    const { searchParams } = useValues(router)
    const skillUrl = (name: string): string => combineUrl(urls.llmAnalyticsSkill(name), searchParams).url

    const columns: LemonTableColumns<LLMSkillListApi> = [
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            width: '20%',
            render: function renderName(_, skill) {
                return (
                    <Link to={skillUrl(skill.name)} className="font-semibold" data-attr="llma-skill-name-link">
                        {skill.name}
                    </Link>
                )
            },
        },
        {
            title: 'Description',
            dataIndex: 'description',
            key: 'description',
            width: '35%',
            render: function renderDescription(description) {
                const text = typeof description === 'string' ? description : ''
                const truncated = text.length > 100 ? text.slice(0, 100) + '...' : text
                return <span className="text-muted text-sm">{truncated || <i>-</i>}</span>
            },
        },
        {
            title: 'Latest author',
            dataIndex: 'created_by',
            render: function renderCreatedBy(_, item) {
                const { created_by } = item
                return (
                    <div className="flex flex-row items-center flex-nowrap">
                        {created_by && <ProfilePicture user={created_by as any} size="md" showName />}
                    </div>
                )
            },
        },
        {
            title: 'Versions',
            dataIndex: 'version_count',
            key: 'version_count',
            width: 100,
            render: function renderVersionCount(_, skill) {
                return <span className="text-muted-alt">{skill.version_count}</span>
            },
        },
        atColumn('created_at', 'Latest version created') as LemonTableColumn<
            LLMSkillListApi,
            keyof LLMSkillListApi | undefined
        >,
        {
            width: 0,
            render: function renderMore(_, skill) {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton to={skillUrl(skill.name)} data-attr="llma-skill-dropdown-view" fullWidth>
                                    View
                                </LemonButton>

                                <AccessControlAction
                                    resourceType={AccessControlResourceType.LlmAnalytics}
                                    minAccessLevel={AccessControlLevel.Editor}
                                >
                                    <LemonButton
                                        onClick={() => {
                                            LemonDialog.openForm({
                                                title: 'Duplicate skill',
                                                initialValues: {
                                                    newName: `${skill.name}-copy`,
                                                },
                                                content: (
                                                    <LemonField name="newName" label="New skill name">
                                                        <LemonInput
                                                            data-attr="llma-skill-duplicate-name"
                                                            placeholder="my-skill-copy"
                                                            maxLength={SKILL_NAME_MAX_LENGTH}
                                                            autoFocus
                                                        />
                                                    </LemonField>
                                                ),
                                                errors: {
                                                    newName: (name: string) => validateSkillName(name),
                                                },
                                                onSubmit: async ({ newName }) => {
                                                    duplicateSkill(skill.name, newName)
                                                },
                                            })
                                        }}
                                        data-attr="llma-skill-dropdown-duplicate"
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
                                        onClick={() => openArchiveSkillDialog(() => deleteSkill(skill.name))}
                                        data-attr="llma-skill-dropdown-delete"
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
                name="Skills"
                description="Manage versioned agent skills that any MCP-connected agent can discover and use."
                resourceType={{ type: 'llm_analytics' }}
                actions={
                    <AccessControlAction
                        resourceType={AccessControlResourceType.LlmAnalytics}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            type="primary"
                            to={skillUrl('new')}
                            icon={<IconPlusSmall />}
                            data-attr="new-skill-button"
                        >
                            New skill
                        </LemonButton>
                    </AccessControlAction>
                }
            />

            <div className="space-y-4">
                <div className="flex gap-x-4 gap-y-2 items-center flex-wrap">
                    <LemonInput
                        type="search"
                        placeholder="Search skills..."
                        value={filters.search}
                        data-attr="skills-search-input"
                        onChange={(value) => setFilters({ search: value })}
                        className="max-w-md"
                    />
                    <div className="text-muted-alt">{skillCountLabel}</div>
                </div>

                <LemonTable
                    loading={skillsLoading}
                    columns={columns}
                    dataSource={skills.results}
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
                    loadingSkeletonRows={SKILLS_PER_PAGE}
                    nouns={['skill', 'skills']}
                />
            </div>
        </SceneContent>
    )
}
