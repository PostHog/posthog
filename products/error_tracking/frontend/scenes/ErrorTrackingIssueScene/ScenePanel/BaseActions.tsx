import { useActions } from 'kea'
import posthog from 'posthog-js'

import { IconShare } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconComment } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { ScenePanelActionsSection } from '~/layout/scenes/SceneLayout'
import { SidePanelTab } from '~/types'

export function BaseActions({ issueId, resourceType }: { issueId: string; resourceType: string }): JSX.Element {
    const hasDiscussions = useFeatureFlag('DISCUSSIONS')
    const { openSidePanel } = useActions(sidePanelLogic)
    return (
        <ScenePanelActionsSection>
            <div className="grid grid-cols-2 gap-1">
                <ButtonPrimitive
                    onClick={() => {
                        if (!hasDiscussions) {
                            posthog.updateEarlyAccessFeatureEnrollment('discussions', true)
                        }
                        openSidePanel(SidePanelTab.Discussion)
                    }}
                    tooltip="Comment"
                    menuItem
                    className="justify-center"
                >
                    <IconComment />
                    <span className="hidden @[200px]:block">Comment</span>
                </ButtonPrimitive>

                <ButtonPrimitive
                    onClick={() => {
                        void copyToClipboard(window.location.origin + urls.errorTrackingIssue(issueId), 'issue link')
                    }}
                    tooltip="Share"
                    data-attr={`${resourceType}-share`}
                    menuItem
                    className="justify-center"
                >
                    <IconShare />
                    <span className="hidden @[200px]:block">Share</span>
                </ButtonPrimitive>
            </div>
        </ScenePanelActionsSection>
    )
}
