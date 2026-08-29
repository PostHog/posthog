import { useActions, useValues } from 'kea'

import { IconGithub, IconThumbsUp } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'
import { PaginationControl } from 'lib/lemon-ui/PaginationControl'
import { usePagination } from 'lib/lemon-ui/PaginationControl/usePagination'
import { SceneExport } from 'scenes/sceneTypes'

import { ProductKey } from '~/queries/schema/schema-general'

import { communitySkillsLogic } from './communitySkillsLogic'
import { TrustTierEnumApi } from './generated/api.schemas'
import type { CommunitySkillListApi, CommunitySkillTemplateVariableApi } from './generated/api.schemas'
import { COMMUNITY_SKILLS_TAB_DESCRIPTION, COMMUNITY_SKILLS_TAB_KEY, SkillsSceneShell } from './SkillsSceneShell'

export const scene: SceneExport = {
    component: CommunitySkillsScene,
    logic: communitySkillsLogic,
    productKey: ProductKey.AI_OBSERVABILITY,
}

const SKILL_GRID_CLASSES = 'grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4'

const TRUST_TIER_TAG: Record<TrustTierEnumApi, { label: string; type: LemonTagType }> = {
    official: { label: 'Official', type: 'success' },
    verified: { label: 'Verified', type: 'completion' },
    community: { label: 'Community', type: 'default' },
}

// GitHub usernames are alphanumeric with single inner hyphens, up to 39 characters.
const GITHUB_HANDLE = /^[a-zA-Z0-9](?:-?[a-zA-Z0-9]){0,38}$/

// The registry stores github_url and author_handle without checking either, so anything we turn
// into a link has to be validated here before a user is invited to click it.
function githubSourceUrl(url: string): string | null {
    try {
        const parsed = new URL(url)
        return parsed.protocol === 'https:' && parsed.hostname === 'github.com' ? parsed.toString() : null
    } catch {
        return null
    }
}

function TrustTierBadge({ tier }: { tier: TrustTierEnumApi }): JSX.Element {
    const config = TRUST_TIER_TAG[tier] ?? TRUST_TIER_TAG.community
    return <LemonTag type={config.type}>{config.label}</LemonTag>
}

// author_handle is the contributor's GitHub username (from the skill's PR/frontmatter).
function AuthorHandle({ handle }: { handle: string }): JSX.Element {
    if (!GITHUB_HANDLE.test(handle)) {
        return <span>@{handle}</span>
    }
    return (
        <Link to={`https://github.com/${handle}`} target="_blank">
            @{handle}
        </Link>
    )
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
        description: 'This is a template. Provide a value for each variable to customize the installed skill.',
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
    const sourceUrl = skill.github_url ? githubSourceUrl(skill.github_url) : null
    const templateVariables = skill.template_variables ?? []
    const isTemplate = templateVariables.length > 0

    return (
        <div className="flex flex-col gap-2 border rounded p-4 bg-bg-light h-full">
            <div className="flex items-start justify-between gap-2">
                <h3 className="font-semibold m-0">{skill.name}</h3>
                <div className="flex items-center gap-1 shrink-0">
                    {isTemplate ? <LemonTag type="highlight">Template</LemonTag> : null}
                    <TrustTierBadge tier={skill.trust_tier} />
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
                    {skill.author_handle ? <AuthorHandle handle={skill.author_handle} /> : null}
                    {sourceUrl ? (
                        <Link to={sourceUrl} target="_blank" className="flex items-center gap-1">
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

function CommunitySkillsGrid({ skills, loading }: { skills: CommunitySkillListApi[]; loading: boolean }): JSX.Element {
    if (loading && skills.length === 0) {
        return (
            <div className={SKILL_GRID_CLASSES}>
                {Array.from({ length: 6 }, (_, index) => (
                    <LemonSkeleton key={index} className="h-40 w-full" />
                ))}
            </div>
        )
    }

    if (skills.length === 0) {
        return <div className="text-muted text-center p-8">No community skills match your filters yet.</div>
    }

    return (
        <div className={SKILL_GRID_CLASSES}>
            {skills.map((skill) => (
                <CommunitySkillCard key={skill.slug} skill={skill} />
            ))}
        </div>
    )
}

export function CommunitySkillsScene(): JSX.Element {
    return (
        <SkillsSceneShell
            activeTabKey={COMMUNITY_SKILLS_TAB_KEY}
            description={COMMUNITY_SKILLS_TAB_DESCRIPTION}
            content={<CommunitySkillsContent />}
        />
    )
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
                <LemonSelect<TrustTierEnumApi | ''>
                    value={filters.trust_tier}
                    onChange={(trust_tier) => setFilters({ trust_tier })}
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

            <CommunitySkillsGrid skills={displaySkills} loading={skillsLoading} />

            <PaginationControl {...paginationState} nouns={['skill', 'skills']} />
        </div>
    )
}
