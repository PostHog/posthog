import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { useRef } from 'react'

import { IconPlus, IconTerminal, IconUpload } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { llmSkillsLogic } from './llmSkillsLogic'

const RESOURCE_TYPE = 'llm-skills'

interface SkillsSceneMenuBarProps {
    /** Community skills is its own scene, with no skills list logic and no title actions. */
    isCommunity: boolean
}

export function SkillsSceneMenuBar(props: SkillsSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    if (!enabled) {
        return null
    }
    return props.isCommunity ? <SceneActions actions={[]} dataAttrKey={RESOURCE_TYPE} /> : <SkillsSceneMenuBarInner />
}

function SkillsSceneMenuBarInner(): JSX.Element {
    const { importing } = useValues(llmSkillsLogic)
    const { importSkill, setConnectModalOpen } = useActions(llmSkillsLogic)
    const { searchParams } = useValues(router)
    const fileInputRef = useRef<HTMLInputElement | null>(null)
    const accessDisabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.LlmSkill, AccessControlLevel.Editor) ?? undefined
    const importDisabledReason = accessDisabledReason ?? (importing ? 'Importing a skill' : undefined)
    const openFilePicker = (): void => fileInputRef.current?.click()

    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-new-skill`,
            label: 'New skill',
            icon: <IconPlus />,
            disabledReason: accessDisabledReason,
            onSelect: () => router.actions.push(combineUrl(urls.skill('new'), searchParams).url),
            pinned: { order: 3, variant: 'primary', dataAttr: 'new-skill-button' },
        },
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-import`,
            label: 'Import',
            icon: <IconUpload />,
            tooltip: 'Import a skill from a spec-compliant .zip',
            opensFloatingUi: true,
            disabledReason: importDisabledReason,
            onSelect: openFilePicker,
            pinned: {
                order: 2,
                variant: 'secondary',
                dataAttr: 'import-skill-button',
                render: () => (
                    <Button
                        variant="outline"
                        onClick={openFilePicker}
                        loading={importing}
                        disabledReason={accessDisabledReason}
                        data-attr="import-skill-button"
                        tooltip="Import a skill from a spec-compliant .zip"
                    >
                        <IconUpload />
                        Import
                    </Button>
                ),
            },
        },
        {
            group: 'view',
            id: `${RESOURCE_TYPE}-menubar-connect-coding-agent`,
            label: 'Load skills in your agent',
            icon: <IconTerminal />,
            opensFloatingUi: true,
            onSelect: () => setConnectModalOpen(true),
            pinned: { order: 1, variant: 'secondary', dataAttr: 'connect-coding-agent-button' },
        },
    ]

    return (
        <>
            <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
            <input
                ref={fileInputRef}
                type="file"
                accept=".zip,application/zip"
                className="hidden"
                onChange={(e) => {
                    const file = e.currentTarget.files?.[0]
                    if (file) {
                        importSkill(file)
                    }
                    // Reset so selecting the same file again re-triggers onChange.
                    e.currentTarget.value = ''
                }}
            />
        </>
    )
}
