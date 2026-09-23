import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton, LemonCollapse, LemonTag } from '@posthog/lemon-ui'

import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import type { LLMSkillApi } from './generated/api.schemas'
import { skillPublishPreviewLogic } from './skillPublishPreviewLogic'

export function PublishToCommunityContents({
    skillName,
    onPreviewChange,
}: {
    skillName: string
    onPreviewChange: (preview: LLMSkillApi | null) => void
}): JSX.Element {
    const { publishPreview, publishPreviewLoading } = useValues(skillPublishPreviewLogic({ skillName }))
    const { loadPublishPreview } = useActions(skillPublishPreviewLogic({ skillName }))

    useEffect(() => {
        onPreviewChange(publishPreview)
    }, [onPreviewChange, publishPreview])

    return (
        <>
            <div className="flex flex-col gap-1 rounded border p-2 bg-primary-highlight">
                <div className="flex items-center gap-2">
                    <span className="font-semibold">Visibility</span>
                    <span>Public on GitHub</span>
                    <LemonTag type="danger">Public</LemonTag>
                </div>
                {publishPreviewLoading ? (
                    <LemonSkeleton active className="h-4 w-3/5" />
                ) : publishPreview ? (
                    <>
                        <div>
                            <span className="font-semibold">Version</span> v{publishPreview.version}
                        </div>
                        <LemonCollapse
                            embedded
                            size="small"
                            panels={[
                                {
                                    key: 'files',
                                    header: 'Review files',
                                    content: (
                                        <ul className="m-0 pl-4 list-disc font-mono text-xs max-h-40 overflow-y-auto break-all">
                                            <li>SKILL.md</li>
                                            {publishPreview.files.map((file) => (
                                                <li key={file.path}>{file.path}</li>
                                            ))}
                                        </ul>
                                    ),
                                },
                            ]}
                        />
                    </>
                ) : (
                    <div className="flex items-center gap-2">
                        <span className="text-secondary">Could not load the version and file list.</span>
                        <LemonButton size="small" onClick={loadPublishPreview}>
                            Retry
                        </LemonButton>
                    </div>
                )}
            </div>
            <LemonField name="consent">
                {({ value, onChange }) => (
                    <LemonCheckbox
                        checked={!!value}
                        onChange={onChange}
                        disabledReason={
                            !publishPreview ? 'Wait for the version and file list before you publish' : undefined
                        }
                        data-attr="llma-publish-consent"
                        label="I reviewed this skill and can share it publicly"
                    />
                )}
            </LemonField>
        </>
    )
}
