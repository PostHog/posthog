import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { combineUrl, router } from 'kea-router'

import { IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, LemonTag, LemonTextArea, Link } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { NotFound } from 'lib/components/NotFound'
import { dayjs } from 'lib/dayjs'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, LLMSkillVersionSummary } from '~/types'

import { SKILL_NAME_MAX_LENGTH, SkillLogicProps, SkillMode, isSkill, llmSkillLogic } from './llmSkillLogic'

export const scene: SceneExport<SkillLogicProps> = {
    component: LLMSkillScene,
    logic: llmSkillLogic,
    productKey: ProductKey.LLM_ANALYTICS,
    paramsToProps: ({ params: { name }, searchParams }) => ({
        skillName: name && name !== 'new' ? name : 'new',
        mode: searchParams?.edit === 'true' ? SkillMode.Edit : SkillMode.View,
        selectedVersion: searchParams?.version ? Number(searchParams.version) || null : null,
    }),
}

function openArchiveDialog(onConfirm: () => void): void {
    LemonDialog.open({
        title: 'Archive skill?',
        description: 'All versions of this skill will be archived. This action cannot be undone.',
        primaryButton: { children: 'Archive', status: 'danger', onClick: onConfirm },
        secondaryButton: { children: 'Cancel' },
    })
}

export function LLMSkillScene(): JSX.Element {
    const {
        shouldDisplaySkeleton,
        skillLoading,
        versionsLoading,
        isSkillFormSubmitting,
        isSkillMissing,
        isNewSkill,
        skillForm,
        isViewMode,
        skill,
        isHistoricalVersion,
        versions,
        canLoadMoreVersions,
    } = useValues(llmSkillLogic)
    const { searchParams } = useValues(router)

    const { submitSkillForm, deleteSkill, setMode, setSkillFormValues, loadMoreVersions } = useActions(llmSkillLogic)

    if (isSkillMissing) {
        return <NotFound object="skill" />
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
                name={skill && 'name' in skill ? skill.name : 'Skill'}
                resourceType={{ type: 'llm_analytics' }}
                isLoading={skillLoading}
                actions={
                    <>
                        {isSkill(skill) && skill.is_latest ? (
                            <AccessControlAction
                                resourceType={AccessControlResourceType.LlmAnalytics}
                                minAccessLevel={AccessControlLevel.Editor}
                            >
                                <LemonButton
                                    type="primary"
                                    icon={<IconPencil />}
                                    onClick={() => setMode(SkillMode.Edit)}
                                    size="small"
                                    data-attr="llma-skill-edit-button"
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
                                        if (isSkill(skill)) {
                                            setSkillFormValues({
                                                name: skill.name,
                                                description: skill.description,
                                                body: skill.body,
                                                license: skill.license || '',
                                                compatibility: skill.compatibility || '',
                                            })
                                            setMode(SkillMode.Edit)
                                        }
                                    }}
                                    size="small"
                                    data-attr="llma-skill-use-as-latest-button"
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
                                onClick={() => openArchiveDialog(deleteSkill)}
                                size="small"
                                data-attr="llma-skill-delete-button"
                            >
                                Archive
                            </LemonButton>
                        </AccessControlAction>
                    </>
                }
            />

            <div className="flex flex-col gap-6 xl:flex-row">
                <div className="min-w-0 flex-1">
                    <SkillViewDetails />
                </div>

                {!isNewSkill && (
                    <SkillVersionSidebar
                        skillName={isSkill(skill) ? skill.name : ''}
                        skill={isSkill(skill) ? skill : null}
                        versions={versions}
                        versionsLoading={versionsLoading}
                        canLoadMoreVersions={canLoadMoreVersions}
                        loadMoreVersions={loadMoreVersions}
                        searchParams={searchParams ?? {}}
                    />
                )}
            </div>
        </SceneContent>
    ) : (
        <Form id="skill-form" formKey="skillForm" logic={llmSkillLogic}>
            <SceneContent>
                <SceneTitleSection
                    name={skillForm.name || 'New skill'}
                    resourceType={{ type: 'llm_analytics' }}
                    isLoading={skillLoading}
                    actions={
                        <>
                            <LemonButton
                                type="secondary"
                                onClick={() => {
                                    if (isNewSkill) {
                                        router.actions.push(urls.llmAnalyticsSkills())
                                    } else {
                                        setMode(SkillMode.View)
                                    }
                                }}
                                disabledReason={isSkillFormSubmitting ? 'Saving...' : undefined}
                                size="small"
                                data-attr="llma-skill-cancel-button"
                            >
                                Cancel
                            </LemonButton>

                            <AccessControlAction
                                resourceType={AccessControlResourceType.LlmAnalytics}
                                minAccessLevel={AccessControlLevel.Editor}
                            >
                                <LemonButton
                                    type="primary"
                                    onClick={submitSkillForm}
                                    loading={isSkillFormSubmitting}
                                    size="small"
                                    data-attr={isNewSkill ? 'skill-create-button' : 'skill-save-button'}
                                >
                                    {isNewSkill ? 'Create skill' : 'Publish version'}
                                </LemonButton>
                            </AccessControlAction>

                            {!isNewSkill && (
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.LlmAnalytics}
                                    minAccessLevel={AccessControlLevel.Editor}
                                >
                                    <LemonButton
                                        type="secondary"
                                        status="danger"
                                        icon={<IconTrash />}
                                        onClick={() => openArchiveDialog(deleteSkill)}
                                        size="small"
                                        data-attr="llma-skill-delete-button"
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
                        <SkillEditForm isHistoricalVersion={isHistoricalVersion} />
                    </div>

                    {!isNewSkill && (
                        <SkillVersionSidebar
                            skillName={isSkill(skill) ? skill.name : ''}
                            skill={isSkill(skill) ? skill : null}
                            versions={versions}
                            versionsLoading={versionsLoading}
                            canLoadMoreVersions={canLoadMoreVersions}
                            loadMoreVersions={loadMoreVersions}
                            searchParams={searchParams ?? {}}
                        />
                    )}
                </div>
            </SceneContent>
        </Form>
    )
    return content
}

function SkillViewDetails(): JSX.Element {
    const { skill } = useValues(llmSkillLogic)

    if (!skill || !isSkill(skill)) {
        return <></>
    }

    return (
        <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-2">
                <LemonTag type="highlight" size="small">
                    v{skill.version}
                </LemonTag>
                {skill.is_latest ? (
                    <LemonTag type="success" size="small">
                        Latest
                    </LemonTag>
                ) : (
                    <LemonTag type="muted" size="small">
                        Historical
                    </LemonTag>
                )}
                <span className="text-secondary text-sm">
                    This skill has {skill.version_count} published version{skill.version_count === 1 ? '' : 's'}.
                </span>
            </div>

            <div>
                <label className="text-xs font-semibold uppercase text-secondary">Name</label>
                <p className="font-mono">{skill.name}</p>
            </div>

            <div>
                <label className="text-xs font-semibold uppercase text-secondary">Description</label>
                <p className="text-sm">{skill.description}</p>
            </div>

            {(skill.license || skill.compatibility) && (
                <div className="grid gap-3 sm:grid-cols-2">
                    {skill.license && (
                        <div>
                            <label className="text-xs font-semibold uppercase text-secondary">License</label>
                            <p className="text-sm">{skill.license}</p>
                        </div>
                    )}
                    {skill.compatibility && (
                        <div>
                            <label className="text-xs font-semibold uppercase text-secondary">Compatibility</label>
                            <p className="text-sm">{skill.compatibility}</p>
                        </div>
                    )}
                </div>
            )}

            {skill.allowed_tools && skill.allowed_tools.length > 0 && (
                <div>
                    <label className="text-xs font-semibold uppercase text-secondary">Allowed tools</label>
                    <div className="mt-1 flex flex-wrap gap-1">
                        {skill.allowed_tools.map((tool) => (
                            <LemonTag key={tool} type="highlight" size="small">
                                {tool}
                            </LemonTag>
                        ))}
                    </div>
                </div>
            )}

            <div>
                <label className="text-xs font-semibold uppercase text-secondary">Skill body</label>
                <LemonMarkdown className="mt-1 rounded border bg-bg-light p-3" generateHeadingIds>
                    {skill.body}
                </LemonMarkdown>
            </div>

            {skill.files && skill.files.length > 0 && (
                <div>
                    <label className="text-xs font-semibold uppercase text-secondary">Bundled files</label>
                    <div className="mt-1 space-y-1">
                        {skill.files.map((file) => (
                            <div key={file.path} className="flex items-center gap-2 rounded border px-3 py-1.5 text-sm">
                                <span className="font-mono">{file.path}</span>
                                <span className="text-muted-alt text-xs">{file.content_type}</span>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            <div className="grid max-w-3xl gap-3 text-sm text-secondary sm:grid-cols-2">
                <div>Published {dayjs(skill.created_at).format('MMM D, YYYY h:mm A')}</div>
                <div>First version created {dayjs(skill.first_version_created_at).format('MMM D, YYYY h:mm A')}</div>
            </div>
        </div>
    )
}

function SkillEditForm({ isHistoricalVersion }: { isHistoricalVersion: boolean }): JSX.Element {
    const { isNewSkill } = useValues(llmSkillLogic)

    return (
        <div className="mt-4 max-w-3xl space-y-4">
            {isHistoricalVersion && (
                <div className="rounded border border-warning bg-warning-highlight p-3 text-sm">
                    You are publishing a new latest version from a historical version. The original version will remain
                    unchanged.
                </div>
            )}

            <LemonField
                name="name"
                label="Name"
                help={
                    isNewSkill
                        ? `Lowercase letters, numbers, and hyphens only. Max ${SKILL_NAME_MAX_LENGTH} characters. Cannot be changed later.`
                        : 'This name is used to fetch the skill from your code.'
                }
            >
                <LemonInput
                    placeholder="my-skill-name"
                    maxLength={SKILL_NAME_MAX_LENGTH}
                    fullWidth
                    disabledReason={!isNewSkill ? 'Skill name cannot be changed after creation' : undefined}
                />
            </LemonField>

            <LemonField
                name="description"
                label="Description"
                help="Explain what this skill does and when to use it. Agents use this to discover the right skill for a task."
            >
                <LemonTextArea
                    placeholder="Extract PDF text, fill forms, merge files. Use when handling PDFs."
                    maxLength={1024}
                    minRows={2}
                    maxRows={4}
                />
            </LemonField>

            <LemonField
                name="body"
                label="Skill body"
                help="The main instruction content (SKILL.md body). Write markdown that tells agents how to perform the task."
            >
                <LemonTextArea
                    placeholder="# My Skill&#10;&#10;## When to use&#10;Use this skill when...&#10;&#10;## Steps&#10;1. First...&#10;2. Then..."
                    minRows={10}
                    className="font-mono"
                />
            </LemonField>

            <LemonField name="license" label="License" help="Optional. License name or reference.">
                <LemonInput placeholder="Apache-2.0" fullWidth />
            </LemonField>

            <LemonField
                name="compatibility"
                label="Compatibility"
                help="Optional. Environment requirements (intended product, system packages, network access)."
            >
                <LemonInput placeholder="Requires git, docker, and internet access" fullWidth />
            </LemonField>
        </div>
    )
}

function SkillVersionSidebar({
    skillName,
    skill,
    versions,
    versionsLoading,
    canLoadMoreVersions,
    loadMoreVersions,
    searchParams,
}: {
    skillName: string
    skill: { id: string; version: number; version_count: number } | null
    versions: LLMSkillVersionSummary[]
    versionsLoading: boolean
    canLoadMoreVersions: boolean
    loadMoreVersions: () => void
    searchParams: Record<string, any>
}): JSX.Element {
    return (
        <aside className="w-full shrink-0 xl:sticky xl:top-4 xl:mt-3 xl:w-80">
            <div className="rounded border bg-surface-primary p-4">
                <div className="mb-3 flex items-center justify-between">
                    <div>
                        <h3 className="font-semibold">Version history</h3>
                        <p className="text-sm text-secondary">
                            {versions.length} of {skill?.version_count ?? versions.length} loaded
                        </p>
                    </div>
                </div>

                <div className="max-h-[28rem] space-y-2 overflow-y-auto pr-1">
                    {versions.map((versionSkill) => {
                        const selected = skill?.id === versionSkill.id
                        const cleanedParams = { ...searchParams }
                        delete cleanedParams.edit
                        const versionUrl = combineUrl(urls.llmAnalyticsSkill(skillName), {
                            ...cleanedParams,
                            version: versionSkill.is_latest ? undefined : versionSkill.version,
                        }).url

                        return (
                            <Link
                                key={versionSkill.id}
                                to={versionUrl}
                                className={`block rounded border p-3 no-underline ${
                                    selected
                                        ? 'border-primary bg-primary-highlight'
                                        : 'border-primary/10 hover:bg-fill-secondary'
                                }`}
                                data-attr={`llma-skill-version-link-${versionSkill.version}`}
                            >
                                <div className="mb-1 flex items-center justify-between">
                                    <div className="flex items-center gap-2">
                                        <span className="font-mono text-sm">v{versionSkill.version}</span>
                                        {versionSkill.is_latest ? (
                                            <LemonTag type="success" size="small">
                                                Latest
                                            </LemonTag>
                                        ) : null}
                                    </div>
                                </div>
                                <div className="text-xs text-secondary">
                                    {dayjs(versionSkill.created_at).format('MMM D, YYYY h:mm A')}
                                </div>
                                {versionSkill.created_by?.email ? (
                                    <div className="mt-1 text-xs text-secondary">{versionSkill.created_by.email}</div>
                                ) : null}
                            </Link>
                        )
                    })}
                </div>

                {canLoadMoreVersions ? (
                    <LemonButton
                        className="mt-3 w-full"
                        type="secondary"
                        onClick={loadMoreVersions}
                        loading={versionsLoading}
                        data-attr="llma-skill-load-more-versions"
                    >
                        Load more versions
                    </LemonButton>
                ) : null}
            </div>
        </aside>
    )
}
