import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { useMemo, useRef } from 'react'

import { IconDownload, IconPlusSmall, IconUpload } from '@posthog/icons'
import { LemonDivider, LemonModal, LemonSwitch, LemonTabs, LemonTag, Link } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet/CodeSnippet'
import { MemberSelect } from 'lib/components/MemberSelect'
import { dayjs } from 'lib/dayjs'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Spinner } from 'lib/lemon-ui/Spinner'
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

import type { LLMSkillListApi } from 'products/skills/frontend/generated/api.schemas'

import {
    DEFAULT_SKILLS_TAB_KEY,
    SKILLS_GROUP_LIMIT,
    SKILLS_PER_PAGE,
    SkillGroupNode,
    SkillGroupTree,
    llmSkillsLogic,
    skillTabUrl,
} from './llmSkillsLogic'
import { SKILL_NAME_MAX_LENGTH, validateSkillName } from './skillConstants'
import { openArchiveSkillDialog } from './skillSceneComponents'

export const scene: SceneExport = {
    component: LLMSkillsScene,
    logic: llmSkillsLogic,
    productKey: ProductKey.AI_OBSERVABILITY,
}

// Mirrors `metadata.seeded_by` stamped by the Signals scout harness (kept local so the skills
// product needn't depend on the signals product). Its presence marks a canonical scout.
const HARNESS_SEEDED_BY = 'signals_scout_harness'

function isCanonicalScout(skill: LLMSkillListApi): boolean {
    return (skill.metadata as Record<string, unknown> | undefined)?.seeded_by === HARNESS_SEEDED_BY
}

function buildSkillColumns(
    skillUrl: (name: string) => string,
    duplicateSkill: (name: string, newName: string) => void,
    deleteSkill: (name: string) => void,
    downloadSkillZip: (name: string) => void,
    options?: { showScoutOrigin?: boolean }
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
        ...(options?.showScoutOrigin
            ? ([
                  {
                      title: 'Origin',
                      key: 'origin',
                      width: 110,
                      render: function renderOrigin(_, skill) {
                          const canonical = isCanonicalScout(skill)
                          return (
                              <LemonTag type={canonical ? 'completion' : 'default'}>
                                  {canonical ? 'Canonical' : 'Custom'}
                              </LemonTag>
                          )
                      },
                  },
              ] as LemonTableColumns<LLMSkillListApi>)
            : []),
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

                                <LemonButton
                                    icon={<IconDownload />}
                                    onClick={() => downloadSkillZip(skill.name)}
                                    data-attr="llma-skill-dropdown-download"
                                    fullWidth
                                >
                                    Download .zip
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

function MarketplaceCredentialSection(): JSX.Element {
    const { marketplaceCommand, codexCommand, marketplaceState, marketplaceLoading, issuingCredential } =
        useValues(llmSkillsLogic)
    const { issueMarketplaceCommand } = useActions(llmSkillsLogic)

    if (marketplaceLoading && !marketplaceState) {
        return (
            <div className="flex items-center gap-2 text-sm text-secondary">
                <Spinner /> Checking your skill store connection…
            </div>
        )
    }

    const justIssued = !!marketplaceState?.token
    const alreadyConnected = !!marketplaceState?.connected && !justIssued

    return (
        <>
            {justIssued ? (
                <LemonBanner type="warning" className="text-sm">
                    This token is shown <b>once</b>. It is <b>read-only</b> and scoped to skills only (
                    <code>llm_skill:read</code>) — it can't touch anything else. It's tied to your account and
                    automatically stops working if you lose access to this project. Manage or revoke it anytime in{' '}
                    <Link to={urls.settings('user-api-keys')}>Settings → Personal API keys</Link>.
                </LemonBanner>
            ) : alreadyConnected ? (
                <LemonBanner type="info" className="text-sm">
                    You already have a skill store credential
                    {marketplaceState?.mask_value ? (
                        <>
                            {' '}
                            (<code>{marketplaceState.mask_value}</code>)
                        </>
                    ) : null}
                    {marketplaceState?.created_at ? <> from {dayjs(marketplaceState.created_at).fromNow()}</> : null}.
                    Existing setups keep working — the token can't be shown again. Setting up a new machine? Generate an
                    install command below.
                </LemonBanner>
            ) : (
                <p className="m-0 text-sm text-secondary">
                    We'll mint a dedicated <b>read-only</b> credential (scope <code>llm_skill:read</code> only — it can
                    read this project's skills and nothing else), just for you, and drop it straight into a
                    ready-to-paste command.
                </p>
            )}
            {!justIssued && (
                <div>
                    <AccessControlAction
                        resourceType={AccessControlResourceType.LlmAnalytics}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            type="primary"
                            onClick={() => issueMarketplaceCommand(alreadyConnected)}
                            loading={issuingCredential}
                            data-attr="generate-marketplace-credential-button"
                        >
                            {alreadyConnected
                                ? 'Generate an install command (replaces your old token)'
                                : 'Generate read-only credential & command'}
                        </LemonButton>
                    </AccessControlAction>
                </div>
            )}
            <div className="flex flex-col gap-1">
                <p className="m-0 text-xs font-semibold text-secondary">Claude Code</p>
                <CodeSnippet language={Language.Bash} thing="Claude Code command">
                    {marketplaceCommand}
                </CodeSnippet>
                <p className="m-0 text-xs text-secondary">
                    Run each line in Claude Code — skills then appear as <code>/posthog-skill-store:&lt;name&gt;</code>,
                    auto-updating as you publish.
                </p>
            </div>
            <div className="flex flex-col gap-1">
                <p className="m-0 text-xs font-semibold text-secondary">Codex</p>
                <CodeSnippet language={Language.Bash} thing="Codex command">
                    {codexCommand}
                </CodeSnippet>
                <p className="m-0 text-xs text-secondary">
                    Run both lines in your terminal — the same marketplace, added to Codex and installed. Codex loads
                    the skills automatically.
                </p>
            </div>
        </>
    )
}

function ConnectToClaudeCodeModal(): JSX.Element {
    const { connectModalOpen } = useValues(llmSkillsLogic)
    const { setConnectModalOpen } = useActions(llmSkillsLogic)

    return (
        <LemonModal
            isOpen={connectModalOpen}
            onClose={() => setConnectModalOpen(false)}
            title="Connect a coding agent"
            description="Install your team's skills into Claude Code or Codex with automatic updates – or let any MCP-connected agent load them directly."
            width={640}
        >
            <div className="flex flex-col gap-4">
                <section className="flex flex-col gap-2">
                    <h4 className="m-0 font-semibold">Plugin marketplace (Claude Code &amp; Codex)</h4>
                    <MarketplaceCredentialSection />
                </section>

                <LemonDivider />

                <section className="flex flex-col gap-2">
                    <h4 className="m-0 font-semibold">Any agent (PostHog MCP)</h4>
                    <p className="m-0 text-sm text-secondary">
                        If the PostHog MCP is connected, an agent can list and load these skills directly via its{' '}
                        <code>skill-*</code> tools — no marketplace needed. Just ask:
                    </p>
                    <CodeSnippet language={Language.Text} thing="agent prompt">
                        List my PostHog skills, then load the one that fits this task.
                    </CodeSnippet>
                </section>
            </div>
        </LemonModal>
    )
}

export function LLMSkillsScene(): JSX.Element {
    const { setFilters, deleteSkill, duplicateSkill, downloadSkillZip, importSkill, setConnectModalOpen } =
        useActions(llmSkillsLogic)
    const {
        skills,
        skillsLoading,
        sorting,
        pagination,
        filters,
        skillCountLabel,
        groupedSkills,
        importing,
        activeTabKey,
        activeCategory,
        activeTabDescription,
        visibleCategoryTabs,
    } = useValues(llmSkillsLogic)
    const { searchParams } = useValues(router)
    const skillUrl = (name: string): string => combineUrl(urls.skill(name), searchParams).url
    const fileInputRef = useRef<HTMLInputElement | null>(null)

    const showScoutOrigin = activeCategory === 'scout'

    // Memoize columns so the array reference doesn't change every render — otherwise every
    // nested LemonTable inside the grouped tree reconciles on each parent re-render.
    const columns = useMemo(
        () => buildSkillColumns(skillUrl, duplicateSkill, deleteSkill, downloadSkillZip, { showScoutOrigin }),
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [searchParams, duplicateSkill, deleteSkill, downloadSkillZip, showScoutOrigin]
    )

    const showGroupedView = filters.group_by_prefix && groupedSkills && !skillsLoading
    const showGroupedLoadingSkeleton = filters.group_by_prefix && skillsLoading
    const truncated = filters.group_by_prefix && skills.count > skills.results.length

    return (
        <SceneContent>
            <input
                ref={fileInputRef}
                type="file"
                accept=".zip,application/zip"
                className="hidden"
                data-attr="import-skill-file-input"
                onChange={(e) => {
                    const file = e.currentTarget.files?.[0]
                    if (file) {
                        importSkill(file)
                    }
                    // Reset so selecting the same file again re-triggers onChange.
                    e.currentTarget.value = ''
                }}
            />
            <ConnectToClaudeCodeModal />
            <SceneTitleSection
                name="Skills"
                description={activeTabDescription}
                resourceType={{ type: 'llm_analytics' }}
                actions={
                    <>
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => setConnectModalOpen(true)}
                            data-attr="connect-coding-agent-button"
                        >
                            Load skills in your agent
                        </LemonButton>
                        <AccessControlAction
                            resourceType={AccessControlResourceType.LlmAnalytics}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconUpload />}
                                onClick={() => fileInputRef.current?.click()}
                                loading={importing}
                                data-attr="import-skill-button"
                                tooltip="Import a skill from a spec-compliant .zip"
                            >
                                Import
                            </LemonButton>
                        </AccessControlAction>
                        <AccessControlAction
                            resourceType={AccessControlResourceType.LlmAnalytics}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonButton
                                type="primary"
                                size="small"
                                to={skillUrl('new')}
                                icon={<IconPlusSmall />}
                                data-attr="new-skill-button"
                            >
                                New skill
                            </LemonButton>
                        </AccessControlAction>
                    </>
                }
            />

            {visibleCategoryTabs.length > 0 && (
                <LemonTabs
                    activeKey={activeTabKey}
                    onChange={(key) => router.actions.push(skillTabUrl(key))}
                    tabs={[
                        { key: DEFAULT_SKILLS_TAB_KEY, label: 'Skills' },
                        ...visibleCategoryTabs.map((tab) => ({ key: tab.key, label: tab.label })),
                    ]}
                />
            )}

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
