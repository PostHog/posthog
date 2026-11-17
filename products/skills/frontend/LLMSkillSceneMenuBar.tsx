import { useActions, useValues } from 'kea'

import { IconArchive, IconDownload, IconPencil, IconShare, IconUpload, IconX } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { openPublishToCommunityDialog } from 'lib/components/openPublishToCommunityDialog'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { SkillMode, isSkill, llmSkillLogic } from './llmSkillLogic'
import { llmSkillsLogic } from './llmSkillsLogic'
import { openArchiveSkillDialog, openRenameSkillDialog } from './skillDialogs'

const RESOURCE_TYPE = 'llm-skill'
const SAVING_REASON = 'Saving…'
const DOWNLOAD_TOOLTIP = 'Download this skill as a spec-compliant .zip (SKILL.md + bundled files)'

interface LLMSkillSceneMenuBarProps {
    /** The read-only view, as opposed to the edit form. */
    view: boolean
    communitySkillsEnabled: boolean
    publishDisabledReason: string | undefined
    renameDisabledReason: string | undefined
}

export function LLMSkillSceneMenuBar(props: LLMSkillSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <LLMSkillSceneMenuBarInner {...props} /> : null
}

function LLMSkillSceneMenuBarInner({
    view,
    communitySkillsEnabled,
    publishDisabledReason,
    renameDisabledReason,
}: LLMSkillSceneMenuBarProps): JSX.Element {
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
    const accessDisabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.LlmSkill, AccessControlLevel.Editor) ?? undefined

    const publishLabel = isNewSkill ? 'Create skill' : nextVersion ? `Publish v${nextVersion}` : 'Publish version'
    const noChangesReason =
        !isNewSkill && !isHistoricalVersion && !isSkillFormDirty ? 'No changes to publish' : undefined

    const actions: SceneAction[] = !view
        ? [
              {
                  group: 'edit',
                  section: 'save',
                  id: `${RESOURCE_TYPE}-menubar-publish`,
                  label: publishLabel,
                  icon: <IconUpload />,
                  disabledReason: accessDisabledReason ?? (isSkillFormSubmitting ? SAVING_REASON : noChangesReason),
                  onSelect: isNewSkill ? submitSkillForm : requestPublish,
                  pinned: {
                      order: 3,
                      variant: 'primary',
                      dataAttr: isNewSkill ? 'skill-create-button' : 'skill-save-button',
                      render: () => (
                          <Button
                              variant="primary"
                              onClick={isNewSkill ? submitSkillForm : requestPublish}
                              loading={isSkillFormSubmitting}
                              disabledReason={accessDisabledReason ?? noChangesReason}
                              data-attr={isNewSkill ? 'skill-create-button' : 'skill-save-button'}
                          >
                              {publishLabel}
                          </Button>
                      ),
                  },
              },
              {
                  group: 'edit',
                  section: 'save',
                  id: `${RESOURCE_TYPE}-menubar-cancel`,
                  label: 'Cancel',
                  icon: <IconX />,
                  disabledReason: isSkillFormSubmitting ? SAVING_REASON : undefined,
                  onSelect: () => cancelEditing(),
                  pinned: { order: 2, variant: 'secondary', dataAttr: 'llma-skill-cancel-button' },
              },
          ]
        : [
              {
                  group: 'edit',
                  section: 'version',
                  id: `${RESOURCE_TYPE}-menubar-new-version`,
                  label: 'New version',
                  icon: <IconPencil />,
                  tooltip: isHistoricalVersion ? 'Start a new version from this historical version' : undefined,
                  disabledReason: accessDisabledReason,
                  onSelect: () => {
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
                  },
                  pinned: { order: 3, variant: 'primary', dataAttr: 'llma-skill-new-version-button' },
              },
              ...(isSkill(skill)
                  ? ([
                        {
                            group: 'edit',
                            // pinned: data-attr values are wire strings
                            id: 'llma-skill-rename-button',
                            label: 'Rename',
                            icon: <IconPencil />,
                            opensFloatingUi: true,
                            disabledReason:
                                accessDisabledReason ?? (renamingSkill ? 'Renaming…' : renameDisabledReason),
                            onSelect: () => openRenameSkillDialog(skill.name, renameSkill),
                        },
                        {
                            group: 'file',
                            section: 'export',
                            id: `${RESOURCE_TYPE}-menubar-download-zip`,
                            label: 'Download .zip',
                            icon: <IconDownload />,
                            tooltip: DOWNLOAD_TOOLTIP,
                            disabledReason: downloadingZip ? 'Downloading' : undefined,
                            onSelect: downloadSkill,
                            pinned: {
                                order: 2,
                                variant: 'secondary',
                                dataAttr: 'llma-skill-download-zip-button',
                                render: () => (
                                    <Button
                                        variant="outline"
                                        onClick={downloadSkill}
                                        loading={downloadingZip}
                                        tooltip={DOWNLOAD_TOOLTIP}
                                        data-attr="llma-skill-download-zip-button"
                                    >
                                        <IconDownload />
                                        Download .zip
                                    </Button>
                                ),
                            },
                        },
                        ...(communitySkillsEnabled
                            ? ([
                                  {
                                      group: 'file',
                                      section: 'share',
                                      id: 'llma-skill-publish-community-button',
                                      label: 'Publish to PostHog community',
                                      icon: <IconShare />,
                                      opensFloatingUi: true,
                                      disabledReason: accessDisabledReason ?? publishDisabledReason,
                                      onSelect: () =>
                                          openPublishToCommunityDialog({
                                              skillName: skill.name,
                                              githubLogin,
                                              onPublish: publishToCommunity,
                                          }),
                                  },
                              ] satisfies SceneAction[])
                            : []),
                    ] satisfies SceneAction[])
                  : []),
              {
                  group: 'file',
                  section: 'delete',
                  id: 'llma-skill-delete-button',
                  label: 'Archive',
                  icon: <IconArchive />,
                  destructive: true,
                  disabledReason: accessDisabledReason,
                  onSelect: () => openArchiveSkillDialog(deleteSkill),
              },
          ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
