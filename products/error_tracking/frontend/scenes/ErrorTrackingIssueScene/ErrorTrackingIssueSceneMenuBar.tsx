import { IconCopy } from '@posthog/icons'

import { SceneComment } from 'lib/components/Scenes/SceneComment'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import {
    SceneMenuBar,
    SceneMenuBarItem,
    SceneMenuBarMenu,
    SceneMenuBarPopover,
} from '~/layout/scenes/components/SceneMenuBar'
import { ScenePanelLabel } from '~/layout/scenes/SceneLayout'
import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'

import { ExternalReferences } from '../../components/ExternalReferences'
import { ErrorTrackingIssueSceneEditMenu } from './ErrorTrackingIssueSceneEditMenu'

interface ErrorTrackingIssueSceneMenuBarProps {
    issue: ErrorTrackingRelationalIssue
}

export function ErrorTrackingIssueSceneMenuBar(props: ErrorTrackingIssueSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <ErrorTrackingIssueSceneMenuBarInner {...props} /> : null
}

function ErrorTrackingIssueSceneMenuBarInner({ issue }: ErrorTrackingIssueSceneMenuBarProps): JSX.Element {
    const hasIssueSplitting = useFeatureFlag('ERROR_TRACKING_ISSUE_SPLITTING')

    return (
        <SceneMenuBar className="shrink-0">
            <SceneMenuBarMenu label="File" dataAttr="error-tracking-issue-menubar-file">
                <SceneMenuBarItem
                    onClick={() => void copyToClipboard(urls.absolute(urls.errorTrackingIssue(issue.id)), 'issue link')}
                    data-attr="error-tracking-issue-menubar-copy-link"
                >
                    <IconCopy />
                    Copy link
                </SceneMenuBarItem>
            </SceneMenuBarMenu>
            {hasIssueSplitting && <ErrorTrackingIssueSceneEditMenu issueId={issue.id} />}
            <SceneMenuBarPopover label="Metadata" dataAttr="error-tracking-issue-menubar-metadata">
                <div className="flex flex-col gap-2">
                    <SceneActivityIndicator at={issue.first_seen} prefix="First seen" />
                    <ScenePanelLabel title="External references">
                        <ExternalReferences />
                    </ScenePanelLabel>
                    <SceneComment dataAttrKey="issue" />
                </div>
            </SceneMenuBarPopover>
        </SceneMenuBar>
    )
}
