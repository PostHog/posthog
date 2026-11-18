import { useActions, useValues } from 'kea'

import { IconDownload, IconEllipsis, IconPencil } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { openPublishToCommunityDialog } from 'lib/components/openPublishToCommunityDialog'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { SkillMode, isSkill, llmSkillLogic } from './llmSkillLogic'
import { llmSkillsLogic } from './llmSkillsLogic'
import { openArchiveSkillDialog, openRenameSkillDialog } from './skillSceneComponents'

export interface QuillLLMSkillActionsProps {
    /** The read-only view, as opposed to the edit form. */
    view: boolean
    communitySkillsEnabled: boolean
    publishDisabledReason: string | undefined
    renameDisabledReason: string | undefined
}

export function QuillLLMSkillActions({
    view,
    communitySkillsEnabled,
    publishDisabledReason,
    renameDisabledReason,
}: QuillLLMSkillActionsProps): JSX.Element {
    const {
        isSkillFormSubmitting,
        isNewSkill,
        skill,
        isHistoricalVersion,
        downloadingZip,
        isSkillFormDirty,
        nextVersion,
        renamingSkill,
    } = useValues(llmSkillLogic)
    const { githubLogin } = useValues(llmSkillsLogic)
    const { publishToCommunity } = useActions(llmSkillsLogic)
    const {
        submitSkillForm,
        requestPublish,
        deleteSkill,
        renameSkill,
        setMode,
        setSkillFormValues,
        downloadSkill,
        cancelEditing,
    } = useActions(llmSkillLogic)
    const editAccessDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.LlmSkill,
        AccessControlLevel.Editor
    )

    if (!view) {
        return (
            <>
                <Button
                    variant="outline"
                    onClick={() => cancelEditing()}
                    disabledReason={isSkillFormSubmitting ? 'Saving…' : undefined}
                    data-attr="llma-skill-cancel-button"
                >
                    Cancel
                </Button>
                <AccessControlAction
                    resourceType={AccessControlResourceType.LlmSkill}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <Button
                        variant="primary"
                        onClick={isNewSkill ? submitSkillForm : requestPublish}
                        loading={isSkillFormSubmitting}
                        disabledReason={
                            !isNewSkill && !isHistoricalVersion && !isSkillFormDirty
                                ? 'No changes to publish'
                                : undefined
                        }
                        data-attr={isNewSkill ? 'skill-create-button' : 'skill-save-button'}
                    >
                        {isNewSkill ? 'Create skill' : nextVersion ? `Publish v${nextVersion}` : 'Publish version'}
                    </Button>
                </AccessControlAction>
            </>
        )
    }

    const publishReason = editAccessDisabledReason || publishDisabledReason
    const renameReason = editAccessDisabledReason || (renamingSkill ? 'Renaming…' : renameDisabledReason)

    return (
        <>
            {isSkill(skill) && (
                <Button
                    variant="outline"
                    onClick={downloadSkill}
                    loading={downloadingZip}
                    tooltip="Download this skill as a spec-compliant .zip (SKILL.md + bundled files)"
                    data-attr="llma-skill-download-zip-button"
                >
                    <IconDownload />
                    Download .zip
                </Button>
            )}
            <AccessControlAction
                resourceType={AccessControlResourceType.LlmSkill}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <Button
                    variant="primary"
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
                    tooltip={isHistoricalVersion ? 'Start a new version from this historical version' : undefined}
                    data-attr="llma-skill-new-version-button"
                >
                    <IconPencil />
                    New version
                </Button>
            </AccessControlAction>
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <Button
                            variant="default"
                            size="icon"
                            aria-label="More"
                            tooltip="More"
                            data-attr="more-button"
                        />
                    }
                >
                    <IconEllipsis />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                    {communitySkillsEnabled && isSkill(skill) && (
                        <DropdownMenuItem
                            disabledReason={publishReason}
                            onClick={() =>
                                openPublishToCommunityDialog({
                                    skillName: skill.name,
                                    githubLogin,
                                    onPublish: publishToCommunity,
                                })
                            }
                            data-attr="llma-skill-publish-community-button"
                        >
                            Publish to PostHog community…
                        </DropdownMenuItem>
                    )}
                    {isSkill(skill) && (
                        <DropdownMenuItem
                            disabledReason={renameReason}
                            onClick={() => openRenameSkillDialog(skill.name, renameSkill)}
                            data-attr="llma-skill-rename-button"
                        >
                            Rename
                        </DropdownMenuItem>
                    )}
                    <AccessControlAction
                        resourceType={AccessControlResourceType.LlmSkill}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <DropdownMenuItem
                            variant="destructive"
                            onClick={() => openArchiveSkillDialog(deleteSkill)}
                            data-attr="llma-skill-delete-button"
                        >
                            Archive
                        </DropdownMenuItem>
                    </AccessControlAction>
                </DropdownMenuContent>
            </DropdownMenu>
        </>
    )
}
