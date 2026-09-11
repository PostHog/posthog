import { useActions, useValues } from 'kea'
import { Suspense } from 'react'

import { LemonButton, LemonModal, LemonTag } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { lazyWithRetry } from 'lib/utils/retryImport'

import { LemonDialog } from '~/lib/lemon-ui/LemonDialog'

import type { SkillFormFileValues } from './llmSkillLogic'
import { isSkill, llmSkillLogic } from './llmSkillLogic'
import { PublishToCommunityContents } from './PublishToCommunityContents'
import { SKILL_NAME_MAX_LENGTH, validateSkillName } from './skillConstants'

export { LLMSkillsScene } from './LLMSkillsScene'
export { LLMSkillScene } from './LLMSkillScene'

const MonacoDiffEditor = lazyWithRetry(() => import('lib/components/MonacoDiffEditor'))

export function openArchiveSkillDialog(onConfirm: () => void): void {
    LemonDialog.open({
        title: 'Archive skill?',
        description: 'All versions of this skill will be archived. This action cannot be undone.',
        primaryButton: { children: 'Archive', status: 'danger', onClick: onConfirm },
        secondaryButton: { children: 'Cancel' },
    })
}

/** Collect the new name, then hand it to `onRename`. */
export function openRenameSkillDialog(skillName: string, onRename: (newName: string) => void): void {
    LemonDialog.openForm({
        title: 'Rename skill',
        description:
            "Agents call the skill by its name, and the name is also its URL and its folder in the zip export. Renaming keeps the skill's version history and owners.",
        initialValues: { newName: skillName },
        content: (
            <LemonField name="newName" label="New skill name">
                <LemonInput
                    data-attr="llma-skill-rename-name"
                    placeholder="my-skill-name"
                    maxLength={SKILL_NAME_MAX_LENGTH}
                    autoFocus
                />
            </LemonField>
        ),
        errors: {
            newName: (name: string) => validateSkillName(name),
        },
        onSubmit: ({ newName }) => onRename(newName),
    })
}

interface PublishToCommunityOptions {
    expected_skill_id: string
    expected_version: number
    display_name?: string
    tags?: string[]
    author_handle?: string
}

/** Owner-only on the backend, so mirror that here instead of letting a click come back a 403.
 * Shared so the list view and the single-skill view guard the trigger identically. */
export function publishToCommunityDisabledReason({
    ownerUuids,
    currentUserUuid,
    publishing,
    isHistoricalVersion,
}: {
    ownerUuids: string[]
    currentUserUuid: string | undefined
    publishing: boolean
    isHistoricalVersion?: boolean
}): string | undefined {
    if (publishing) {
        return 'Publishing…'
    }
    if (ownerUuids.length === 0) {
        return 'Add an owner before you publish this skill'
    }
    if (!currentUserUuid || !ownerUuids.includes(currentUserUuid)) {
        return "Only the skill's owners can publish it"
    }
    // The backend shares the latest version by name, so block sharing from a historical version to
    // avoid pushing content the user is not looking at.
    if (isHistoricalVersion) {
        return 'Switch to the latest version to publish'
    }
    return undefined
}

/** Collect the publish fields, then hand them to `onPublish`. Shared so the list view and the
 * single-skill view open the identical dialog. */
export function openPublishToCommunityDialog({
    skillName,
    githubLogin,
    onPublish,
}: {
    skillName: string
    githubLogin: string | null
    onPublish: (skillName: string, options: PublishToCommunityOptions) => void
}): void {
    let expectedSkill: { id: string; version: number } | null = null

    LemonDialog.openForm({
        title: 'Publish to the PostHog community?',
        description: 'All PostHog users can find and use this skill. Its contents will also be public on GitHub.',
        initialValues: {
            display_name: skillName.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
            tags: '',
            // Prefill with the user's resolved GitHub handle when we have one; the field stays
            // editable so users without a linked GitHub identity can still type one (free-text fallback).
            author_handle: githubLogin ?? '',
            consent: false,
        },
        content: (
            <div className="flex flex-col gap-2">
                <PublishToCommunityContents
                    skillName={skillName}
                    onPreviewChange={(preview) => {
                        expectedSkill = preview ? { id: preview.id, version: preview.version } : null
                    }}
                />
                <LemonField name="display_name" label="Display name">
                    <LemonInput data-attr="llma-publish-display-name" autoFocus />
                </LemonField>
                <LemonField name="tags" label="Tags (comma-separated)">
                    <LemonInput data-attr="llma-publish-tags" placeholder="web-analytics, triage" />
                </LemonField>
                <LemonField name="author_handle" label="Your GitHub handle (optional)">
                    <LemonInput data-attr="llma-publish-author-handle" placeholder="octocat" />
                </LemonField>
            </div>
        ),
        errors: {
            consent: (consent: boolean) =>
                consent ? undefined : 'Review the skill and confirm that you can share it publicly',
        },
        primaryButtonProps: { children: 'Publish to community' },
        onSubmit: ({ display_name, tags, author_handle }) => {
            if (expectedSkill === null) {
                return
            }
            onPublish(skillName, {
                expected_skill_id: expectedSkill.id,
                expected_version: expectedSkill.version,
                display_name: display_name?.trim() || undefined,
                tags: tags
                    ? tags
                          .split(',')
                          .map((t: string) => t.trim())
                          .filter(Boolean)
                    : undefined,
                author_handle: author_handle?.trim() || undefined,
            })
        },
    })
}

interface FileChanges {
    added: string[]
    removed: string[]
    changed: string[]
}

function diffFiles(baseline: SkillFormFileValues[], current: SkillFormFileValues[]): FileChanges {
    const baselineByPath = new Map(baseline.map((f) => [f.path, f]))
    const currentByPath = new Map(current.map((f) => [f.path, f]))
    const added = current.filter((f) => !baselineByPath.has(f.path)).map((f) => f.path)
    const removed = baseline.filter((f) => !currentByPath.has(f.path)).map((f) => f.path)
    const changed = current
        .filter((f) => {
            const base = baselineByPath.get(f.path)
            return base && (base.content !== f.content || base.content_type !== f.content_type)
        })
        .map((f) => f.path)
    return { added, removed, changed }
}

export function SkillPublishReviewModal(): JSX.Element | null {
    const {
        isPublishReviewOpen,
        skill,
        skillForm,
        skillFormBaseline,
        nextVersion,
        isSkillFormSubmitting,
        versionDescription,
    } = useValues(llmSkillLogic)
    const { closePublishReview, submitSkillForm, setVersionDescription } = useActions(llmSkillLogic)

    if (!isSkill(skill)) {
        return null
    }

    const publishLabel = nextVersion ? `Publish v${nextVersion}` : 'Publish version'
    const isDescriptionChanged = skillForm.description !== skill.description
    const fileChanges = diffFiles(skillFormBaseline?.files ?? [], skillForm.files)
    const hasFileChanges =
        fileChanges.added.length > 0 || fileChanges.removed.length > 0 || fileChanges.changed.length > 0

    return (
        <LemonModal
            isOpen={isPublishReviewOpen}
            onClose={closePublishReview}
            title="Review changes"
            description={`Comparing v${skill.version} with your edits. Publishing creates ${
                nextVersion ? `v${nextVersion}` : 'a new version'
            }. Previous versions stay unchanged.`}
            width={880}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closePublishReview}
                        disabledReason={isSkillFormSubmitting ? 'Publishing…' : undefined}
                        data-attr="llma-skill-review-back-button"
                    >
                        Back to editing
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitSkillForm}
                        loading={isSkillFormSubmitting}
                        data-attr="llma-skill-review-publish-button"
                    >
                        {publishLabel}
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-3">
                <div className="overflow-hidden rounded border" data-attr="llma-skill-publish-review-diff">
                    <Suspense
                        fallback={
                            <div className="space-y-2 p-4">
                                <LemonSkeleton active className="h-4 w-full" />
                                <LemonSkeleton active className="h-4 w-3/4" />
                            </div>
                        }
                    >
                        <MonacoDiffEditor
                            original={skill.body}
                            value={skillForm.body}
                            modified={skillForm.body}
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
                {isDescriptionChanged ? (
                    <div data-attr="llma-skill-publish-review-description-diff">
                        <div className="mb-1 flex items-center gap-2">
                            <span className="text-sm font-semibold">Description</span>
                            <LemonTag type="warning" size="small">
                                Changed
                            </LemonTag>
                        </div>
                        <div className="overflow-hidden rounded border">
                            <Suspense
                                fallback={
                                    <div className="space-y-2 p-4">
                                        <LemonSkeleton active className="h-4 w-full" />
                                    </div>
                                }
                            >
                                <MonacoDiffEditor
                                    original={skill.description}
                                    value={skillForm.description}
                                    modified={skillForm.description}
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
                    </div>
                ) : null}
                {hasFileChanges ? (
                    <div data-attr="llma-skill-publish-review-file-changes">
                        <div className="mb-1 flex items-center gap-2">
                            <span className="text-sm font-semibold">Bundled files</span>
                            <LemonTag type="warning" size="small">
                                Changed
                            </LemonTag>
                        </div>
                        <div className="space-y-1 rounded border p-3 text-sm">
                            {fileChanges.added.map((path) => (
                                <div key={`added-${path}`} className="flex items-center gap-2">
                                    <LemonTag type="success" size="small">
                                        Added
                                    </LemonTag>
                                    <span className="font-mono">{path}</span>
                                </div>
                            ))}
                            {fileChanges.removed.map((path) => (
                                <div key={`removed-${path}`} className="flex items-center gap-2">
                                    <LemonTag type="danger" size="small">
                                        Removed
                                    </LemonTag>
                                    <span className="font-mono">{path}</span>
                                </div>
                            ))}
                            {fileChanges.changed.map((path) => (
                                <div key={`changed-${path}`} className="flex items-center gap-2">
                                    <LemonTag type="warning" size="small">
                                        Changed
                                    </LemonTag>
                                    <span className="font-mono">{path}</span>
                                </div>
                            ))}
                        </div>
                    </div>
                ) : null}
                <LemonField.Pure label="What changed?" help="Optional. Shown in the version history.">
                    <LemonInput
                        value={versionDescription}
                        onChange={setVersionDescription}
                        placeholder="e.g. Added a troubleshooting section"
                        maxLength={400}
                        data-attr="llma-skill-version-description-input"
                    />
                </LemonField.Pure>
            </div>
        </LemonModal>
    )
}
