import { SceneName } from 'lib/components/Scenes/SceneName'
import { useActions, useValues } from 'kea'
import { ScenePanelActions, ScenePanelCommonActions, ScenePanelDivider } from '~/layout/scenes/SceneLayout'
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
import { IconAI, IconCheckCircle, IconChevronDown, IconEllipsis, IconRefresh } from '@posthog/icons'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'
import { AssigneeSelect } from './components/Assignee/AssigneeSelect'
import { AssigneeIconDisplay, AssigneeLabelDisplay } from './components/Assignee/AssigneeDisplay'
import { ErrorTrackingIssue, ErrorTrackingIssueAssignee } from '~/queries/schema'
import { Label } from 'lib/ui/Label/Label'
import { IssueStatus, LabelIndicator, STATUS_TOOLTIP, StatusIndicator, StatusIntent } from './components/Indicator'
import { GenericSelect } from './components/GenericSelect'
import { ISSUE_STATUS_OPTIONS } from './utils'
import { LemonSelect } from '@posthog/lemon-ui'

export const ErrorTrackingIssueScenePanel = (): JSX.Element | null => {
    const { issue } = useValues(errorTrackingIssueSceneLogic)
    const { updateName, updateDescription, updateAssignee, updateStatus } = useActions(errorTrackingIssueSceneLogic)

    return issue ? (
        <div>
            <SceneName defaultValue={issue.name ?? ''} onSave={updateName} dataAttr="issue-name" />
            <SceneDescription
                defaultValue={issue.description ?? ''}
                onSave={updateDescription}
                dataAttr="insight-description"
            />
            <IssueStatus status={issue.status} />
            {issue.status === 'active' && <IssueAssignee assignee={issue.assignee} onChange={updateAssignee} />}
            <SceneActivityIndicator at={issue.first_seen} prefix="First seen" />

            <ScenePanelDivider />

            <ScenePanelCommonActions>
                <SceneCommonButtons
                    comment
                    share={{
                        onClick: () => {
                            void copyToClipboard(
                                window.location.origin + urls.errorTrackingIssue(issue.id),
                                'issue link'
                            )
                        },
                    }}
                />
            </ScenePanelCommonActions>

            <ScenePanelActions>
                {/* <IssueExternalReference /> */}

                <ButtonPrimitive fullWidth>
                    <IconAI />
                    Fix with AI
                </ButtonPrimitive>
            </ScenePanelActions>
        </div>
    ) : null
}

const IssueStatus = ({
    status,
    onChange,
}: {
    status: ErrorTrackingIssue['status']
    onChange: (status: ErrorTrackingIssue['status']) => void
}): JSX.Element => {
    return (
        <div>
            <div className="gap-0">
                <Label intent="menu">Status</Label>

                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <ButtonPrimitive fullWidth className="flex justify-between">
                            <StatusIndicator status={status} withTooltip={true} />
                            <IconChevronDown />
                        </ButtonPrimitive>
                    </DropdownMenuTrigger>

                    <DropdownMenuContent loop matchTriggerWidth>
                        {status == 'active' ? (
                            <>
                                <DropdownMenuItem asChild>
                                    <ButtonPrimitive menuItem onClick={() => onChange('resolved')}>
                                        <StatusIndicator status="resolved" intention />
                                    </ButtonPrimitive>
                                </DropdownMenuItem>
                                <DropdownMenuItem asChild>
                                    <ButtonPrimitive menuItem onClick={() => onChange('suppressed')}>
                                        <StatusIndicator status="suppressed" intention />
                                    </ButtonPrimitive>
                                </DropdownMenuItem>
                            </>
                        ) : (
                            <DropdownMenuItem asChild>
                                <ButtonPrimitive menuItem onClick={() => onChange('active')}>
                                    <StatusIndicator status="active" intention />
                                </ButtonPrimitive>
                            </DropdownMenuItem>
                        )}
                    </DropdownMenuContent>
                </DropdownMenu>
            </div>
        </div>
    )
}

const IssueAssignee = ({
    assignee,
    onChange,
}: {
    assignee: ErrorTrackingIssueAssignee | null
    onChange: (assignee: ErrorTrackingIssueAssignee | null) => void
}): JSX.Element => {
    return (
        <div>
            <div className="gap-0">
                <Label intent="menu">Assignee</Label>
                <AssigneeSelect assignee={assignee} onChange={onChange}>
                    {(anyAssignee) => (
                        <ButtonPrimitive menuItem fullWidth className="flex justify-between">
                            <div className="flex items-center">
                                <AssigneeIconDisplay assignee={anyAssignee} size="small" />
                                <AssigneeLabelDisplay assignee={anyAssignee} className="ml-1" size="small" />
                            </div>
                            <IconChevronDown />
                        </ButtonPrimitive>
                    )}
                </AssigneeSelect>
            </div>
        </div>
    )
}

const IssueExternalReference = (): JSX.Element => {
    return <div>Add external reference</div>
}
