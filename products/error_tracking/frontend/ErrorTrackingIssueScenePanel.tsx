import { SceneName } from 'lib/components/Scenes/SceneName'
import { useActions, useValues } from 'kea'
import {
    ScenePanelActions,
    ScenePanelCommonActions,
    ScenePanelDivider,
    ScenePanelMetaInfo,
} from '~/layout/scenes/SceneLayout'
import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { SceneDescription } from 'lib/components/Scenes/SceneDescription'
import { SceneCommonButtons } from 'lib/components/Scenes/SceneCommonButtons'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { ButtonGroupPrimitive, ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { IconAI, IconCheckCircle, IconChevronDown } from '@posthog/icons'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

export const ErrorTrackingIssueScenePanel = (): JSX.Element | null => {
    const { issue } = useValues(errorTrackingIssueSceneLogic)
    const { updateName, updateDescription } = useActions(errorTrackingIssueSceneLogic)

    return issue ? (
        <div>
            {/* <ScenePanel> */}
            <ScenePanelMetaInfo>
                <SceneName defaultValue={issue.name ?? ''} onSave={updateName} dataAttr="issue-name" />
                <SceneDescription
                    defaultValue={issue.description ?? ''}
                    onSave={updateDescription}
                    dataAttr="insight-description"
                />
                <SceneActivityIndicator at={issue.first_seen} prefix="First seen" />
            </ScenePanelMetaInfo>

            <ScenePanelDivider />

            <ScenePanelCommonActions>
                <SceneCommonButtons
                    comment
                    share={{
                        onClick: () => {
                            void copyToClipboard(urls.errorTrackingIssue(issue.id))
                        },
                    }}
                />
            </ScenePanelCommonActions>

            <ScenePanelActions>
                <IssueStatus />
                <IssueAssignee />
                <IssueExternalReference />

                <ButtonPrimitive fullWidth>
                    <IconAI />
                    Fix with AI
                </ButtonPrimitive>
            </ScenePanelActions>
            {/* </ScenePanel> */}
        </div>
    ) : null
}

const IssueStatus = (): JSX.Element => {
    return (
        <DropdownMenu>
            <ButtonGroupPrimitive className="text-success">
                <ButtonPrimitive menuItem fullWidth hasSideActionRight>
                    <IconCheckCircle />
                    Resolve issue
                </ButtonPrimitive>
                <DropdownMenuTrigger asChild>
                    <ButtonPrimitive iconOnly isSideActionRight>
                        <IconChevronDown />
                    </ButtonPrimitive>
                </DropdownMenuTrigger>
            </ButtonGroupPrimitive>

            <DropdownMenuContent loop align="start">
                <DropdownMenuItem asChild>
                    <ButtonPrimitive variant="danger" size="base" menuItem>
                        Suppress issue
                    </ButtonPrimitive>
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

const IssueAssignee = (): JSX.Element => {
    return <div>Assignee</div>
}

const IssueExternalReference = (): JSX.Element => {
    return <div>Add external reference</div>
}
