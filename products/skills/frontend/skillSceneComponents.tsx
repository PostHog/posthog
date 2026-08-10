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
