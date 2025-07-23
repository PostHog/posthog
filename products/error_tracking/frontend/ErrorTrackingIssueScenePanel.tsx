import { SceneName } from 'lib/components/Scenes/SceneName'
import { useActions, useValues } from 'kea'
import { ScenePanelCommonActions, ScenePanelDivider, ScenePanelLabel } from '~/layout/scenes/SceneLayout'
import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { SceneDescription } from 'lib/components/Scenes/SceneDescription'
import { SceneCommonButtons } from 'lib/components/Scenes/SceneCommonButtons'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { IconChevronDown } from '@posthog/icons'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'
import { AssigneeSelect } from './components/Assignee/AssigneeSelect'
import { AssigneeIconDisplay, AssigneeLabelDisplay } from './components/Assignee/AssigneeDisplay'
import { StatusIndicator } from './components/Indicator'
import { ErrorTrackingIssue, ErrorTrackingIssueAssignee } from '~/queries/schema/schema-general'
import { ExternalReferences } from './components/ExternalReferences'

const RESOURCE_TYPE = 'issue'

export const ErrorTrackingIssueScenePanel = (): JSX.Element | null => {
    const { issue } = useValues(errorTrackingIssueSceneLogic)
    const { updateName, updateDescription, updateAssignee, updateStatus } = useActions(errorTrackingIssueSceneLogic)

    return issue ? (
        <div>
            <SceneName defaultValue={issue.name ?? ''} onSave={updateName} dataAttrKey={RESOURCE_TYPE} />
            <SceneDescription
                defaultValue={issue.description ?? ''}
                onSave={updateDescription}
                dataAttrKey={RESOURCE_TYPE}
            />
            <SceneActivityIndicator at={issue.first_seen} prefix="First seen" />

            <IssueStatusSelect status={issue.status} onChange={updateStatus} />
            {issue.status === 'active' && <IssueAssigneeSelect assignee={issue.assignee} onChange={updateAssignee} />}
            <IssueExternalReference />

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
                    dataAttrKey={RESOURCE_TYPE}
                />
            </ScenePanelCommonActions>
        </div>
    ) : null
}

const IssueStatusSelect = ({
    status,
    onChange,
}: {
    status: ErrorTrackingIssue['status']
    onChange: (status: ErrorTrackingIssue['status']) => void
}): JSX.Element => {
    return (
        <ScenePanelLabel title="Status">
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
                                    <StatusIndicator status="resolved" intent />
                                </ButtonPrimitive>
                            </DropdownMenuItem>
                            <DropdownMenuItem asChild>
                                <ButtonPrimitive menuItem onClick={() => onChange('suppressed')}>
                                    <StatusIndicator status="suppressed" intent />
                                </ButtonPrimitive>
                            </DropdownMenuItem>
                        </>
                    ) : (
                        <DropdownMenuItem asChild>
                            <ButtonPrimitive menuItem onClick={() => onChange('active')}>
                                <StatusIndicator status="active" intent />
                            </ButtonPrimitive>
                        </DropdownMenuItem>
                    )}
                </DropdownMenuContent>
            </DropdownMenu>
        </ScenePanelLabel>
    )
}

const IssueAssigneeSelect = ({
    assignee,
    onChange,
}: {
    assignee: ErrorTrackingIssueAssignee | null
    onChange: (assignee: ErrorTrackingIssueAssignee | null) => void
}): JSX.Element => {
    return (
        <ScenePanelLabel title="Assignee">
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
        </ScenePanelLabel>
    )
}

const IssueExternalReference = (): JSX.Element => {
    return (
        <ScenePanelLabel title="External references">
            <ExternalReferences />
        </ScenePanelLabel>
    )
}
