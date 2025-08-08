import { useActions, useValues } from 'kea'
import { SceneCommonButtons } from 'lib/components/Scenes/SceneCommonButtons'

import { SceneTextInput } from 'lib/components/Scenes/SceneTextInput'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuOpenIndicator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'
import { ScenePanelCommonActions, ScenePanelDivider, ScenePanelLabel } from '~/layout/scenes/SceneLayout'
import { ErrorTrackingIssue, ErrorTrackingIssueAssignee } from '~/queries/schema/schema-general'
import { AssigneeIconDisplay, AssigneeLabelDisplay } from './components/Assignee/AssigneeDisplay'
import { AssigneeSelect } from './components/Assignee/AssigneeSelect'
import { ExternalReferences } from './components/ExternalReferences'
import { StatusIndicator } from './components/Indicator'
import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { SceneTextarea } from 'lib/components/Scenes/SceneTextarea'

const RESOURCE_TYPE = 'issue'

export const ErrorTrackingIssueScenePanel = (): JSX.Element | null => {
    const { issue } = useValues(errorTrackingIssueSceneLogic)
    const { updateName, updateDescription, updateAssignee, updateStatus } = useActions(errorTrackingIssueSceneLogic)

    return issue ? (
        <div className="flex flex-col gap-2">
            <SceneTextInput
                name="name"
                defaultValue={issue.name ?? ''}
                onSave={updateName}
                dataAttrKey={RESOURCE_TYPE}
            />
            <SceneTextarea
                name="description"
                defaultValue={issue.description ?? ''}
                onSave={updateDescription}
                dataAttrKey={RESOURCE_TYPE}
            />

            <IssueStatusSelect status={issue.status} onChange={updateStatus} />
            <IssueAssigneeSelect
                assignee={issue.assignee}
                onChange={updateAssignee}
                disabled={issue.status != 'active'}
            />
            <IssueExternalReference />
            <SceneActivityIndicator at={issue.first_seen} prefix="First seen" />

            {/* Add a div here to break out of the gap-2 */}
            <div>
                <ScenePanelDivider className="mb-0" />

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
                    <ButtonPrimitive fullWidth className="flex justify-between" variant="panel" menuItem>
                        <StatusIndicator status={status} withTooltip={true} />
                        <DropdownMenuOpenIndicator />
                    </ButtonPrimitive>
                </DropdownMenuTrigger>

                <DropdownMenuContent loop matchTriggerWidth>
                    {status === 'active' ? (
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
    disabled,
    onChange,
}: {
    assignee: ErrorTrackingIssueAssignee | null
    disabled: boolean
    onChange: (assignee: ErrorTrackingIssueAssignee | null) => void
}): JSX.Element => {
    return (
        <ScenePanelLabel title="Assignee">
            <AssigneeSelect assignee={assignee} onChange={onChange}>
                {(anyAssignee, isOpen) => (
                    <ButtonPrimitive
                        menuItem
                        fullWidth
                        disabled={disabled}
                        className="flex justify-between"
                        data-state={isOpen ? 'open' : 'closed'}
                        variant="panel"
                    >
                        <div className="flex items-center">
                            <AssigneeIconDisplay assignee={anyAssignee} size="small" />
                            <AssigneeLabelDisplay assignee={anyAssignee} className="ml-1" size="small" />
                        </div>
                        {!disabled && <DropdownMenuOpenIndicator />}
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
