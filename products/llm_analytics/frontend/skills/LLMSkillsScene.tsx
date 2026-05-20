import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { useMemo } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonSwitch, Link } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { MemberSelect } from 'lib/components/MemberSelect'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
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
import { SKILLS_GROUP_LIMIT, SKILLS_PER_PAGE, SkillGroupNode, SkillGroupTree, llmSkillsLogic } from './llmSkillsLogic'
import { SKILL_NAME_MAX_LENGTH, validateSkillName } from './skillConstants'
import { openArchiveSkillDialog } from './skillSceneComponents'

export const scene: SceneExport = {
    component: LLMSkillsScene,
    logic: llmSkillsLogic,
    productKey: ProductKey.LLM_ANALYTICS,
}

function buildSkillColumns(
    skillUrl: (name: string) => string,
    duplicateSkill: (name: string, newName: string) => void,
    deleteSkill: (name: string) => void
): LemonTableColumns<LLMSkillListApi> {
    return [
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
}

function GroupHeader({ node }: { node: SkillGroupNode }): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            <span className="font-mono font-semibold">{node.prefix}</span>
            <span className="text-muted-alt text-xs">
                {node.count} skill{node.count === 1 ? '' : 's'}
            </span>
        </div>
    )
}

function SkillLeafTable({
    skills,
    columns,
}: {
    skills: LLMSkillListApi[]
    columns: LemonTableColumns<LLMSkillListApi>
}): JSX.Element {
    return (
        <LemonTable
            columns={columns}
            dataSource={skills}
            rowKey="id"
            showHeader={false}
            embedded
            size="small"
            nouns={['skill', 'skills']}
        />
    )
}

function SkillGroupPanels({
    groups,
    columns,
}: {
    groups: SkillGroupNode[]
    columns: LemonTableColumns<LLMSkillListApi>
}): JSX.Element {
    return (
        <LemonCollapse
            multiple
            embedded
            size="small"
            panels={groups.map((node) => ({
                key: node.prefix,
                header: <GroupHeader node={node} />,
                dataAttr: `llma-skill-group-${node.prefix}`,
                content: (
                    <div className="flex flex-col gap-2">
                        {node.children.length > 0 && <SkillGroupPanels groups={node.children} columns={columns} />}
                        {node.leaves.length > 0 && <SkillLeafTable skills={node.leaves} columns={columns} />}
                    </div>
                ),
            }))}
        />
    )
}

function GroupedSkillsView({
    tree,
    columns,
}: {
    tree: SkillGroupTree
    columns: LemonTableColumns<LLMSkillListApi>
}): JSX.Element {
    const hasGroups = tree.groups.length > 0
    const hasUngrouped = tree.ungrouped.length > 0

    if (!hasGroups && !hasUngrouped) {
        return (
            <div className="text-muted-alt text-sm p-4 text-center border rounded">
                No skills match the current filters.
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-3">
            {hasGroups && <SkillGroupPanels groups={tree.groups} columns={columns} />}
            {hasUngrouped && (
                <div className="flex flex-col gap-1" data-attr="llma-skill-group-ungrouped">
                    <div className="flex items-center gap-2 px-2">
                        <span className="font-semibold">Ungrouped</span>
                        <span className="text-muted-alt text-xs">
                            {tree.ungrouped.length} skill{tree.ungrouped.length === 1 ? '' : 's'}
                        </span>
                    </div>
                    <SkillLeafTable skills={tree.ungrouped} columns={columns} />
                </div>
            )}
        </div>
    )
}

export function LLMSkillsScene(): JSX.Element {
    const { setFilters, deleteSkill, duplicateSkill } = useActions(llmSkillsLogic)
    const { skills, skillsLoading, sorting, pagination, filters, skillCountLabel, groupedSkills } =
        useValues(llmSkillsLogic)
    const { searchParams } = useValues(router)
    const skillUrl = (name: string): string => combineUrl(urls.llmAnalyticsSkill(name), searchParams).url

    // Memoize columns so the array reference doesn't change every render — otherwise every
    // nested LemonTable inside the grouped tree reconciles on each parent re-render.
    const columns = useMemo(
        () => buildSkillColumns(skillUrl, duplicateSkill, deleteSkill),
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [searchParams, duplicateSkill, deleteSkill]
    )

    const showGroupedView = filters.group_by_prefix && groupedSkills && !skillsLoading
    const showGroupedLoadingSkeleton = filters.group_by_prefix && skillsLoading
    const truncated = filters.group_by_prefix && skills.count > skills.results.length

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
                    <LemonSwitch
                        label="Group by prefix"
                        checked={filters.group_by_prefix}
                        onChange={(checked) => setFilters({ group_by_prefix: checked })}
                        bordered
                        size="small"
                        data-attr="skills-group-by-prefix-toggle"
                    />
                    <div className="text-muted-alt">{skillCountLabel}</div>
                    <div className="flex-1" />
                    <span>
                        <b>Created by</b>
                    </span>
                    <MemberSelect
                        defaultLabel="Any user"
                        value={filters.created_by_id ?? null}
                        size="xsmall"
                        onChange={(user) => setFilters({ created_by_id: user?.id, page: 1 })}
                    />
                </div>

                {filters.group_by_prefix ? (
                    <>
                        {truncated && (
                            <LemonBanner type="warning">
                                Showing the first {skills.results.length} of {skills.count} skills. The grouped view is
                                capped at {SKILLS_GROUP_LIMIT} skills — use search or turn off grouping to see the rest.
                            </LemonBanner>
                        )}
                        {showGroupedLoadingSkeleton ? (
                            <LemonTable
                                loading
                                columns={columns}
                                dataSource={[]}
                                rowKey="id"
                                loadingSkeletonRows={SKILLS_PER_PAGE}
                                nouns={['skill', 'skills']}
                            />
                        ) : (
                            showGroupedView && <GroupedSkillsView tree={groupedSkills!} columns={columns} />
                        )}
                    </>
                ) : (
                    <LemonTable
                        loading={skillsLoading}
                        columns={columns}
                        // Drop the cached results while a reload is in flight if they exceed the
                        // expected page size — otherwise toggling out of grouped mode flashes the
                        // full 500-item payload through the controlled-paginated flat table.
                        dataSource={skillsLoading && skills.results.length > SKILLS_PER_PAGE ? [] : skills.results}
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
                )}
            </div>
        </SceneContent>
    )
}
