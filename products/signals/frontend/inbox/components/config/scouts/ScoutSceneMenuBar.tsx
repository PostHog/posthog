import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import {
    IconClockRewind,
    IconExternal,
    IconGear,
    IconListCheck,
    IconPencil,
    IconRefresh,
    IconUpload,
} from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import {
    SceneMenuBar,
    SceneMenuBarCheckboxItem,
    SceneMenuBarItem,
    SceneMenuBarMenu,
    SceneMenuBarSeparator,
} from '~/layout/scenes/components/SceneMenuBar'
import { ActivityScope } from '~/types'

import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

import { scoutDetailActionsLogic } from '../../../logics/scoutDetailActionsLogic'

// pinned: the `data-attr` prefix of every item, which the menu bar's central capture reports as the item.
const RESOURCE_TYPE = 'scout'

export function ScoutSceneMenuBar({ config }: { config: SignalScoutConfig }): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]) {
        return null
    }
    return <ScoutSceneMenuBarInner config={config} />
}

function ScoutSceneMenuBarInner({ config }: { config: SignalScoutConfig }): JSX.Element {
    const logic = scoutDetailActionsLogic({ skillName: config.skill_name })
    const {
        running,
        updating,
        publishDisabledReason,
        canPublish,
        canEditRubrics,
        noteDisabledReason,
        runNoteDisabledReason,
    } = useValues(logic)
    const { runNow, leaveNote, setEnabled, setRunNoteOpen, publish, openDialog, skillOpened } = useActions(logic)

    return (
        <SceneMenuBar>
            <SceneMenuBarMenu label="File" dataAttr={`${RESOURCE_TYPE}-menubar-file`} disabled={!canPublish}>
                {canPublish && (
                    <SceneMenuBarItem
                        onClick={publish}
                        disabled={!!publishDisabledReason}
                        tooltip={publishDisabledReason}
                        opensFloatingUi
                        data-attr={`${RESOURCE_TYPE}-menubar-publish`}
                    >
                        <IconUpload />
                        Publish to community
                    </SceneMenuBarItem>
                )}
            </SceneMenuBarMenu>
            <SceneMenuBarMenu label="Edit" dataAttr={`${RESOURCE_TYPE}-menubar-edit`}>
                <SceneMenuBarItem
                    onClick={runNow}
                    disabled={running}
                    tooltip={running ? 'Starting a run' : undefined}
                    data-attr={`${RESOURCE_TYPE}-menubar-run-now`}
                >
                    <IconRefresh />
                    Run now
                </SceneMenuBarItem>
                <SceneMenuBarItem
                    onClick={() => setRunNoteOpen(true)}
                    disabled={!!runNoteDisabledReason}
                    tooltip={runNoteDisabledReason}
                    opensFloatingUi
                    data-attr={`${RESOURCE_TYPE}-menubar-run-with-note`}
                >
                    <IconRefresh />
                    Run with a note
                </SceneMenuBarItem>
                <SceneMenuBarItem
                    onClick={leaveNote}
                    disabled={!!noteDisabledReason}
                    tooltip={noteDisabledReason}
                    opensFloatingUi
                    data-attr={`${RESOURCE_TYPE}-menubar-tell-it-something`}
                >
                    <IconPencil />
                    Tell it something
                </SceneMenuBarItem>
                <SceneMenuBarItem
                    onClick={() => openDialog('settings')}
                    opensFloatingUi
                    data-attr={`${RESOURCE_TYPE}-menubar-settings`}
                >
                    <IconGear />
                    Settings
                </SceneMenuBarItem>
                {canEditRubrics && (
                    <SceneMenuBarItem
                        onClick={() => openDialog('rubrics')}
                        opensFloatingUi
                        data-attr={`${RESOURCE_TYPE}-menubar-rubrics`}
                    >
                        <IconListCheck />
                        Rubrics
                    </SceneMenuBarItem>
                )}
                <SceneMenuBarSeparator />
                <SceneMenuBarCheckboxItem
                    checked={config.enabled}
                    onCheckedChange={(checked: boolean) => setEnabled(checked)}
                    disabled={updating}
                    data-attr={`${RESOURCE_TYPE}-menubar-enabled`}
                >
                    Enabled
                </SceneMenuBarCheckboxItem>
            </SceneMenuBarMenu>
            <SceneMenuBarMenu label="View" dataAttr={`${RESOURCE_TYPE}-menubar-view`}>
                <SceneMenuBarItem
                    onClick={() => {
                        skillOpened()
                        router.actions.push(urls.skill(config.skill_name))
                    }}
                    data-attr={`${RESOURCE_TYPE}-menubar-view-skill`}
                >
                    <IconExternal />
                    View skill
                </SceneMenuBarItem>
                <SceneMenuBarItem
                    onClick={() =>
                        router.actions.push(
                            combineUrl(urls.advancedActivityLogs(), {
                                scopes: ActivityScope.SIGNAL_SCOUT_CONFIG,
                                item_ids: config.id,
                            }).url
                        )
                    }
                    data-attr={`${RESOURCE_TYPE}-menubar-activity`}
                >
                    <IconClockRewind />
                    View activity
                </SceneMenuBarItem>
            </SceneMenuBarMenu>
        </SceneMenuBar>
    )
}
