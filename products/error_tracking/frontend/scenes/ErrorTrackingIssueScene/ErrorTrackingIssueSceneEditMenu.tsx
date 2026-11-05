import { useActions } from 'kea'

import { IconFingerprint } from 'lib/lemon-ui/icons'

import { SceneMenuBarItem, SceneMenuBarMenu } from '~/layout/scenes/components/SceneMenuBar'

import { manageFingerprintsLogic } from '../../components/FingerprintPreview/manageFingerprintsLogic'

export function ErrorTrackingIssueSceneEditMenu({ issueId }: { issueId: string }): JSX.Element {
    const { openManage } = useActions(manageFingerprintsLogic({ issueId }))

    return (
        <SceneMenuBarMenu label="Edit" dataAttr="error-tracking-issue-menubar-edit">
            <SceneMenuBarItem
                onClick={openManage}
                opensFloatingUi
                data-attr="error-tracking-issue-menubar-fingerprints"
            >
                <IconFingerprint />
                Manage fingerprints
            </SceneMenuBarItem>
        </SceneMenuBarMenu>
    )
}
