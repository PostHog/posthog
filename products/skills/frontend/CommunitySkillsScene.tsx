import { useActions, useValues } from 'kea'

import { IconGithub, IconThumbsUp } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'
import { PaginationControl } from 'lib/lemon-ui/PaginationControl'
import { usePagination } from 'lib/lemon-ui/PaginationControl/usePagination'
import { SceneExport } from 'scenes/sceneTypes'

import { ProductKey } from '~/queries/schema/schema-general'

import { CommunitySkillTrustTier, communitySkillsLogic } from './communitySkillsLogic'
import type { CommunitySkillListApi, CommunitySkillTemplateVariableApi } from './generated/api.schemas'
import { SkillsSceneShell } from './SkillsSceneShell'

export const scene: SceneExport = {
    component: CommunitySkillsScene,
    logic: communitySkillsLogic,
    productKey: ProductKey.AI_OBSERVABILITY,
}

const TRUST_TIER_TAG: Record<CommunitySkillTrustTier, { label: string; type: LemonTagType }> = {
    official: { label: 'Official', type: 'success' },
    verified: { label: 'Verified', type: 'completion' },
    community: { label: 'Community', type: 'default' },
}

function TrustTierBadge({ tier }: { tier: CommunitySkillTrustTier }): JSX.Element {
    const config = TRUST_TIER_TAG[tier] ?? TRUST_TIER_TAG.community
    return <LemonTag type={config.type}>{config.label}</LemonTag>
}

// A template declares variables that must be bound before install. Collect a value per variable,
// then install with them. Defaults prefill; required variables are guarded.
function openTemplateInstallDialog(
    skill: CommunitySkillListApi,
    variables: readonly CommunitySkillTemplateVariableApi[],
    install: (slug: string, newName?: string, values?: Record<string, string>) => void
): void {
    LemonDialog.openForm({
        title: `Install "${skill.name}"`,
        description: 'This is a template — provide a value for each variable below to customize the installed skill.',
        initialValues: Object.fromEntries(variables.map((v) => [v.name, v.default ?? ''])),
        content: (
            <div className="flex flex-col gap-2">
                {variables.map((v) => (
                    <LemonField key={v.name} name={v.name} label={v.prompt || v.name}>
                        <LemonInput data-attr={`community-skill-template-var-${v.name}`} autoFocus={false} />
                    </LemonField>
                ))}
            </div>
        ),
        errors: Object.fromEntries(
            variables
                .filter((v) => v.is_required)
                .map((v) => [v.name, (value: string) => (!value?.trim() ? 'This variable is required' : undefined)])
        ),
        onSubmit: (values) => install(skill.slug, undefined, values as Record<string, string>),
    })
}

function CommunitySkillCard({ skill }: { skill: CommunitySkillListApi }): JSX.Element {
    const { installingSlugs, votingSlugs } = useValues(communitySkillsLogic)
    const { installSkill, toggleVote } = useActions(communitySkillsLogic)
    const installing = !!installingSlugs[skill.slug]
    const voting = !!votingSlugs[skill.slug]
    const templateVariables = skill.template_variables ?? []
    const isTemplate = templateVariables.length > 0

    return (
        <div className="flex flex-col gap-2 border rounded p-4 bg-bg-light h-full">
            <div className="flex items-start justify-between gap-2">
                <h3 className="font-semibold m-0">{skill.name}</h3>
                <div className="flex items-center gap-1 shrink-0">
                    {isTemplate ? <LemonTag type="highlight">Template</LemonTag> : null}
                    <TrustTierBadge tier={skill.trust_tier as CommunitySkillTrustTier} />
                </div>
            </div>
            <p className="text-muted text-sm grow line-clamp-3">{skill.description}</p>
            <div className="flex flex-wrap gap-1">
                {(skill.tags ?? []).slice(0, 4).map((tag) => (
                    <LemonTag key={tag} type="muted" size="small">
                        {tag}
                    </LemonTag>
                ))}
            </div>
            <div className="flex items-center justify-between gap-2 pt-2 border-t">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-muted text-xs">
                    <span>{skill.install_count} installs</span>
                    {skill.author_handle ? (
                        // author_handle is the contributor's GitHub username (from the skill's PR/frontmatter).
                        <Link to={`https://github.com/${skill.author_handle}`} target="_blank">
                            @{skill.author_handle}
                        </Link>
                    ) : null}
                    {skill.github_url ? (
                        <Link to={skill.github_url} target="_blank" className="flex items-center gap-1">
                            <IconGithub /> View on GitHub
                        </Link>
                    ) : null}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                    <LemonButton
                        size="small"
                        type="tertiary"
                        icon={<IconThumbsUp />}
                        active={skill.has_voted}
                        loading={voting}
                        disabledReason={voting ? 'Saving your vote…' : undefined}
                        onClick={() => toggleVote(skill.slug)}
                        tooltip={skill.has_voted ? 'Remove your vote' : 'Upvote this skill'}
                    >
                        {skill.vote_count}
                    </LemonButton>
                    <LemonButton
                        size="small"
                        type="primary"
                        loading={installing}
                        disabledReason={installing ? 'Installing…' : undefined}
                        onClick={() =>
                            isTemplate
                                ? openTemplateInstallDialog(skill, templateVariables, installSkill)
                                : installSkill(skill.slug)
                        }
                    >
                        {isTemplate ? 'Install…' : 'Install'}
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}

export function CommunitySkillsScene(): JSX.Element {
    return <SkillsSceneShell activeTab="community" content={<CommunitySkillsContent />} />
}

function CommunitySkillsContent(): JSX.Element {
    const { displaySkills, filters, pagination, skillsLoading } = useValues(communitySkillsLogic)
    const { setFilters } = useActions(communitySkillsLogic)
    // Controlled pagination: page changes write the `page` URL param, which urlToAction turns into setFilters.
    const paginationState = usePagination(displaySkills, pagination)

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-2">
                <LemonInput
                    type="search"
                    placeholder="Search skills…"
                    value={filters.search}
                    onChange={(search) => setFilters({ search })}
                    className="grow max-w-100"
                />
                <LemonSelect
                    value={filters.trust_tier}
                    onChange={(trust_tier) => setFilters({ trust_tier: trust_tier as CommunitySkillTrustTier | '' })}
                    options={[
                        { value: '', label: 'All tiers' },
                        { value: 'official', label: 'Official' },
                        { value: 'verified', label: 'Verified' },
                        { value: 'community', label: 'Community' },
                    ]}
                />
                <LemonSelect
                    value={filters.order_by}
                    onChange={(order_by) => setFilters({ order_by })}
                    options={[
                        { value: '-install_count', label: 'Most installed' },
                        { value: '-vote_count', label: 'Top rated' },
                        { value: '-published_at', label: 'Newest' },
                        { value: 'name', label: 'Name (A–Z)' },
                    ]}
                />
            </div>

            {displaySkills.length === 0 && !skillsLoading ? (
                <div className="text-muted text-center p-8">No community skills match your filters yet.</div>
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                    {displaySkills.map((skill) => (
                        <CommunitySkillCard key={skill.slug} skill={skill} />
                    ))}
                </div>
            )}

            <PaginationControl {...paginationState} nouns={['skill', 'skills']} />
        </div>
    )
}
