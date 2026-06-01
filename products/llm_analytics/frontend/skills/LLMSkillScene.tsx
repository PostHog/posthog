import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { combineUrl, router } from 'kea-router'
import { lazy, Suspense, useCallback, useRef, useState } from 'react'

import { IconChevronRight, IconColumns, IconDocument, IconPencil, IconPlus, IconTrash, IconX } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSelect, LemonTag, LemonTextArea, Link } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet/CodeSnippet'
import { NotFound } from 'lib/components/NotFound'
import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ApiConfig } from '~/lib/api'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { MarkdownOutline } from '../components/MarkdownOutline'
import { llmSkillsNameFilesRetrieve } from '../generated/api'
import type { LLMSkillFileApi, LLMSkillFileManifestApi, LLMSkillVersionSummaryApi } from '../generated/api.schemas'
import type { SkillFormFileValues } from './llmSkillLogic'
import { SkillLogicProps, SkillMode, isSkill, llmSkillLogic } from './llmSkillLogic'
import { SKILL_NAME_MAX_LENGTH, SKILL_DESCRIPTION_MAX_LENGTH } from './skillConstants'
import { openArchiveSkillDialog } from './skillSceneComponents'

const MonacoDiffEditor = lazy(() => import('lib/components/MonacoDiffEditor'))

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
        fileContentsLoading,
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
                                onClick={() => openArchiveSkillDialog(deleteSkill)}
                                size="small"
                                data-attr="llma-skill-delete-button"
                            >
                                Archive
                            </LemonButton>
                        </AccessControlAction>
                    </>
                }
            />

            <div className="flex flex-col gap-6 2xl:flex-row">
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
                                        onClick={() => openArchiveSkillDialog(deleteSkill)}
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

                <div className="flex flex-col gap-6 2xl:flex-row">
                    <div className="min-w-0 flex-1">
                        <SkillEditForm
                            isHistoricalVersion={isHistoricalVersion}
                            fileContentsLoading={fileContentsLoading}
                        />
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
    const { skill, isOutlineExpanded, isDiffVisible, canCompareVersions, compareVersionOptions } =
        useValues(llmSkillLogic)
    const { toggleOutlineExpanded, setCompareVersion } = useActions(llmSkillLogic)
    const markdownContainerRef = useRef<HTMLDivElement | null>(null)

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
                <div className="flex items-center gap-2">
                    <label className="text-xs font-semibold uppercase text-secondary">Skill body</label>
                    {canCompareVersions && (
                        <LemonButton
                            size="xsmall"
                            type={isDiffVisible ? 'primary' : 'secondary'}
                            icon={<IconColumns />}
                            onClick={() => {
                                if (isDiffVisible) {
                                    setCompareVersion(null)
                                } else {
                                    const firstOption = compareVersionOptions[0]?.value
                                    const defaultVersion = compareVersionOptions.some(
                                        (o) => o.value === skill.version - 1
                                    )
                                        ? skill.version - 1
                                        : (firstOption ?? null)
                                    setCompareVersion(defaultVersion)
                                }
                            }}
                            data-attr="llma-skill-compare-versions-button"
                        >
                            Compare versions
                        </LemonButton>
                    )}
                </div>
                {isDiffVisible ? (
                    <SkillDiffView />
                ) : (
                    <>
                        <MarkdownOutline
                            markdownText={skill.body}
                            containerRef={markdownContainerRef}
                            className="mt-2"
                            label="Skill outline"
                            tooltipText="Navigate the sections of this skill. Click a heading to scroll to it."
                            dataAttrPrefix="llma-skill"
                            isExpanded={isOutlineExpanded}
                            onToggleExpanded={toggleOutlineExpanded}
                        />
                        <div ref={markdownContainerRef}>
                            <LemonMarkdown className="mt-1 rounded border bg-bg-light p-3" generateHeadingIds>
                                {skill.body}
                            </LemonMarkdown>
                        </div>
                    </>
                )}
            </div>

            {skill.files && skill.files.length > 0 && (
                <div>
                    <label className="text-xs font-semibold uppercase text-secondary">
                        Bundled files ({skill.files.length})
                    </label>
                    <div className="mt-1 space-y-1">
                        {skill.files.map((file) => (
                            <SkillFileViewer
                                key={file.path}
                                skillName={skill.name}
                                file={file}
                                version={skill.is_latest ? undefined : skill.version}
                            />
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

function SkillDiffView(): JSX.Element {
    const { skill, compareSkill, compareSkillLoading, compareVersion, compareVersionOptions } = useValues(llmSkillLogic)
    const { setCompareVersion } = useActions(llmSkillLogic)

    if (!skill || !isSkill(skill)) {
        return <></>
    }

    const currentVersion = skill.version
    const original = compareSkill?.body ?? ''
    const modified = skill.body

    return (
        <div className="mt-2 space-y-3" data-attr="llma-skill-diff-view">
            <div className="flex items-center gap-2">
                <span className="text-sm text-secondary">Comparing</span>
                <LemonSelect
                    size="small"
                    value={compareVersion}
                    options={compareVersionOptions}
                    onChange={(value) => setCompareVersion(value)}
                    data-attr="llma-skill-diff-version-select"
                />
                <span className="text-sm text-secondary">with v{currentVersion} (current)</span>
            </div>
            {compareSkillLoading ? (
                <div className="space-y-2 rounded border p-4">
                    <LemonSkeleton active className="h-4 w-full" />
                    <LemonSkeleton active className="h-4 w-3/4" />
                    <LemonSkeleton active className="h-4 w-1/2" />
                </div>
            ) : !compareSkill ? (
                <LemonBanner type="warning">
                    Failed to load version for comparison. Try selecting a different version.
                </LemonBanner>
            ) : (
                <div className="overflow-hidden rounded border">
                    <Suspense
                        fallback={
                            <div className="space-y-2 p-4">
                                <LemonSkeleton active className="h-4 w-full" />
                                <LemonSkeleton active className="h-4 w-3/4" />
                            </div>
                        }
                    >
                        <MonacoDiffEditor
                            original={original}
                            value={modified}
                            modified={modified}
                            language="markdown"
                            options={{
                                readOnly: true,
                                renderSideBySide: true,
                                minimap: { enabled: false },
                                scrollBeyondLastLine: false,
                                wordWrap: 'on',
                                lineNumbers: 'off',
                                folding: false,
                                hideUnchangedRegions: { enabled: true },
                            }}
                        />
                    </Suspense>
                </div>
            )}
        </div>
    )
}

const LANGUAGE_BY_EXTENSION: Record<string, Language> = {
    py: Language.Python,
    js: Language.JavaScript,
    jsx: Language.JavaScript,
    mjs: Language.JavaScript,
    ts: Language.TypeScript,
    tsx: Language.TypeScript,
    sh: Language.Bash,
    bash: Language.Bash,
    zsh: Language.Bash,
    json: Language.JSON,
    yaml: Language.YAML,
    yml: Language.YAML,
    html: Language.HTML,
    xml: Language.XML,
    sql: Language.SQL,
    rb: Language.Ruby,
    go: Language.Go,
    java: Language.Java,
    kt: Language.Kotlin,
    swift: Language.Swift,
    php: Language.PHP,
    dart: Language.Dart,
    cs: Language.CSharp,
    m: Language.ObjectiveC,
    ex: Language.Elixir,
    exs: Language.Elixir,
    hcl: Language.HCL,
    tf: Language.HCL,
    groovy: Language.Groovy,
}

function getFileLanguage(path: string, contentType?: string): Language | null {
    const templateStripped = path.replace(/\.(template|tmpl|j2)$/i, '')
    const ext = templateStripped.toLowerCase().split('.').pop() ?? ''
    if (ext in LANGUAGE_BY_EXTENSION) {
        return LANGUAGE_BY_EXTENSION[ext]
    }
    if (contentType?.startsWith('application/json')) {
        return Language.JSON
    }
    if (contentType === 'text/x-python') {
        return Language.Python
    }
    if (contentType === 'text/x-shellscript') {
        return Language.Bash
    }
    return null
}

function SkillFileViewer({
    skillName,
    file,
    version,
}: {
    skillName: string
    file: LLMSkillFileManifestApi
    version?: number
}): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const [content, setContent] = useState<string | null>(null)
    const [loading, setLoading] = useState(false)

    const toggleExpand = useCallback(async () => {
        if (expanded) {
            setExpanded(false)
            return
        }
        if (content === null) {
            setLoading(true)
            try {
                const fileData: LLMSkillFileApi = await llmSkillsNameFilesRetrieve(
                    String(ApiConfig.getCurrentTeamId()),
                    skillName,
                    file.path,
                    { version }
                )
                setContent(fileData.content)
            } catch (e) {
                console.error('Failed to load file content', e)
                setContent('Failed to load file content.')
            } finally {
                setLoading(false)
            }
        }
        setExpanded(true)
    }, [expanded, content, skillName, file.path, version])

    const isMarkdown = file.content_type === 'text/markdown' || file.path.endsWith('.md')
    const codeLanguage = isMarkdown ? null : getFileLanguage(file.path, file.content_type)

    return (
        <div className="rounded border">
            <button
                type="button"
                className="flex w-full cursor-pointer items-center gap-2 border-none bg-transparent px-3 py-2 text-left text-sm hover:bg-fill-secondary"
                onClick={toggleExpand}
                data-attr={`llma-skill-file-toggle-${file.path}`}
            >
                <IconChevronRight
                    className={`h-3.5 w-3.5 shrink-0 text-muted transition-transform ${expanded ? 'rotate-90' : ''}`}
                />
                <IconDocument className="h-3.5 w-3.5 shrink-0 text-muted" />
                <span className="font-mono flex-1">{file.path}</span>
                <span className="text-muted-alt text-xs">{file.content_type}</span>
            </button>
            {expanded && (
                <div className="border-t bg-bg-light px-3 py-2">
                    {loading ? (
                        <div className="space-y-2">
                            <LemonSkeleton active className="h-3 w-full" />
                            <LemonSkeleton active className="h-3 w-3/4" />
                            <LemonSkeleton active className="h-3 w-1/2" />
                        </div>
                    ) : content === null ? null : isMarkdown ? (
                        <LemonMarkdown className="text-sm" generateHeadingIds>
                            {content}
                        </LemonMarkdown>
                    ) : codeLanguage !== null ? (
                        <CodeSnippet language={codeLanguage} compact thing={file.path} maxLinesWithoutExpansion={20}>
                            {content}
                        </CodeSnippet>
                    ) : (
                        <pre className="max-h-80 overflow-auto text-xs whitespace-pre-wrap">{content}</pre>
                    )}
                </div>
            )}
        </div>
    )
}

const COMMON_CONTENT_TYPES = [
    { value: 'text/plain', label: 'text/plain' },
    { value: 'text/markdown', label: 'text/markdown' },
    { value: 'text/x-python', label: 'text/x-python' },
    { value: 'text/x-shellscript', label: 'text/x-shellscript' },
    { value: 'application/json', label: 'application/json' },
    { value: 'text/yaml', label: 'text/yaml' },
    { value: 'text/javascript', label: 'text/javascript' },
    { value: 'text/typescript', label: 'text/typescript' },
]

function SkillEditForm({
    isHistoricalVersion,
    fileContentsLoading,
}: {
    isHistoricalVersion: boolean
    fileContentsLoading: boolean
}): JSX.Element {
    const { isNewSkill, skillForm } = useValues(llmSkillLogic)
    const { setSkillFormValues } = useActions(llmSkillLogic)

    const addFile = (): void => {
        setSkillFormValues({
            files: [...skillForm.files, { path: '', content: '', content_type: 'text/plain' }],
        })
    }

    const removeFile = (index: number): void => {
        setSkillFormValues({
            files: skillForm.files.filter((_, i) => i !== index),
        })
    }

    const updateFile = (index: number, field: keyof SkillFormFileValues, value: string): void => {
        const updated = skillForm.files.map((f, i) => (i === index ? { ...f, [field]: value } : f))
        setSkillFormValues({ files: updated })
    }

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
                    data-attr="llma-skill-name-input"
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
                    data-attr="llma-skill-description-input"
                    placeholder="Extract PDF text, fill forms, merge files. Use when handling PDFs."
                    maxLength={SKILL_DESCRIPTION_MAX_LENGTH}
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
                    data-attr="llma-skill-body-input"
                    placeholder="# My Skill&#10;&#10;## When to use&#10;Use this skill when...&#10;&#10;## Steps&#10;1. First...&#10;2. Then..."
                    minRows={10}
                    className="font-mono"
                />
            </LemonField>

            <LemonField name="license" label="License" help="Optional. License name or reference.">
                <LemonInput data-attr="llma-skill-license-input" placeholder="Apache-2.0" maxLength={255} fullWidth />
            </LemonField>

            <LemonField
                name="compatibility"
                label="Compatibility"
                help="Optional. Environment requirements (intended product, system packages, network access)."
            >
                <LemonInput
                    data-attr="llma-skill-compatibility-input"
                    placeholder="Requires git, docker, and internet access"
                    maxLength={500}
                    fullWidth
                />
            </LemonField>

            <div>
                <div className="mb-2 flex items-center justify-between">
                    <div>
                        <label className="text-sm font-semibold">Bundled files</label>
                        <p className="text-xs text-secondary">
                            Scripts, references, or assets bundled with this skill. Files are sent to agents alongside
                            the skill body.
                        </p>
                    </div>
                    <LemonButton
                        type="secondary"
                        icon={<IconPlus />}
                        size="small"
                        onClick={addFile}
                        data-attr="llma-skill-add-file-button"
                    >
                        Add file
                    </LemonButton>
                </div>

                {fileContentsLoading ? (
                    <div className="space-y-2 rounded border p-3">
                        <LemonSkeleton active className="h-3 w-1/3" />
                        <LemonSkeleton active className="h-3 w-full" />
                        <LemonSkeleton active className="h-3 w-2/3" />
                    </div>
                ) : skillForm.files.length === 0 ? (
                    <div className="rounded border border-dashed p-4 text-center text-sm text-secondary">
                        No bundled files. Click "Add file" to include scripts or references.
                    </div>
                ) : (
                    <div className="space-y-3">
                        {skillForm.files.map((file, index) => (
                            <SkillFileEditor
                                key={index}
                                file={file}
                                index={index}
                                onUpdate={updateFile}
                                onRemove={removeFile}
                            />
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
}

function SkillFileEditor({
    file,
    index,
    onUpdate,
    onRemove,
}: {
    file: SkillFormFileValues
    index: number
    onUpdate: (index: number, field: keyof SkillFormFileValues, value: string) => void
    onRemove: (index: number) => void
}): JSX.Element {
    const [collapsed, setCollapsed] = useState(false)

    return (
        <div className="rounded border">
            <div className="flex items-center gap-2 border-b px-3 py-2">
                <button
                    type="button"
                    className="flex cursor-pointer items-center border-none bg-transparent p-0"
                    onClick={() => setCollapsed(!collapsed)}
                >
                    <IconChevronRight
                        className={`h-3.5 w-3.5 shrink-0 text-muted transition-transform ${!collapsed ? 'rotate-90' : ''}`}
                    />
                </button>
                <IconDocument className="h-3.5 w-3.5 shrink-0 text-muted" />
                <span className="font-mono flex-1 text-sm">{file.path || 'New file'}</span>
                <LemonButton
                    icon={<IconX />}
                    size="xsmall"
                    status="danger"
                    onClick={() => onRemove(index)}
                    tooltip="Remove file"
                    data-attr={`llma-skill-remove-file-${index}`}
                />
            </div>
            {!collapsed && (
                <div className="space-y-3 p-3">
                    <div className="flex gap-3">
                        <div className="flex-1">
                            <label className="mb-1 block text-xs font-medium text-secondary">Path</label>
                            <LemonInput
                                data-attr={`llma-skill-file-path-${index}`}
                                value={file.path}
                                onChange={(val) => onUpdate(index, 'path', val)}
                                placeholder="scripts/setup.sh"
                                fullWidth
                                size="small"
                            />
                        </div>
                        <div className="w-48">
                            <label className="mb-1 block text-xs font-medium text-secondary">Content type</label>
                            <LemonSelect
                                data-attr={`llma-skill-file-content-type-${index}`}
                                value={file.content_type}
                                onChange={(val) => onUpdate(index, 'content_type', val)}
                                options={COMMON_CONTENT_TYPES}
                                size="small"
                                fullWidth
                            />
                        </div>
                    </div>
                    <div>
                        <label className="mb-1 block text-xs font-medium text-secondary">Content</label>
                        <LemonTextArea
                            data-attr={`llma-skill-file-content-${index}`}
                            value={file.content}
                            onChange={(val) => onUpdate(index, 'content', val)}
                            placeholder="File content..."
                            minRows={4}
                            className="font-mono"
                        />
                    </div>
                </div>
            )}
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
    versions: LLMSkillVersionSummaryApi[]
    versionsLoading: boolean
    canLoadMoreVersions: boolean
    loadMoreVersions: () => void
    searchParams: Record<string, any>
}): JSX.Element {
    const { compareVersion } = useValues(llmSkillLogic)
    const { setCompareVersion } = useActions(llmSkillLogic)

    return (
        <aside className="w-full shrink-0 2xl:sticky 2xl:top-4 2xl:mt-3 2xl:w-80">
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
                        const isCompareTarget = compareVersion === versionSkill.version
                        const canCompare = skill?.version !== versionSkill.version
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
                                        : isCompareTarget
                                          ? 'border-warning bg-warning-highlight'
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
                                        {isCompareTarget ? (
                                            <LemonTag type="warning" size="small">
                                                Comparing
                                            </LemonTag>
                                        ) : null}
                                    </div>
                                    {canCompare && (
                                        <LemonButton
                                            size="xsmall"
                                            noPadding
                                            icon={<IconColumns />}
                                            tooltip={
                                                isCompareTarget
                                                    ? 'Stop comparing'
                                                    : `Compare with v${versionSkill.version}`
                                            }
                                            onClick={(e) => {
                                                e.preventDefault()
                                                e.stopPropagation()
                                                setCompareVersion(isCompareTarget ? null : versionSkill.version)
                                            }}
                                            data-attr={`llma-skill-compare-version-${versionSkill.version}`}
                                        />
                                    )}
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
