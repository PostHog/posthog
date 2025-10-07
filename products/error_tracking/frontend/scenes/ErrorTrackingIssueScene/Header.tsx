import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { IconEllipsis, IconShare } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconComment } from 'lib/lemon-ui/icons'
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

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ErrorTrackingIssue, ErrorTrackingIssueAssignee } from '~/queries/schema/schema-general'
import { SidePanelTab } from '~/types'

import { AssigneeIconDisplay, AssigneeLabelDisplay } from '../../components/Assignee/AssigneeDisplay'
import { AssigneeSelect } from '../../components/Assignee/AssigneeSelect'
import { LabelIndicator, StatusIndicator } from '../../components/Indicators'
import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'

const RESOURCE_TYPE = 'issue'

export const Header = (): JSX.Element => {
    const { issue, issueId, issueLoading } = useValues(errorTrackingIssueSceneLogic)
    const { updateName, updateDescription, updateAssignee, updateStatus } = useActions(errorTrackingIssueSceneLogic)
    const hasIssueSplitting = useFeatureFlag('ERROR_TRACKING_ISSUE_SPLITTING')
    const hasDiscussions = useFeatureFlag('DISCUSSIONS')
    const { openSidePanel } = useActions(sidePanelLogic)

    return (
        <div className="flex flex-col gap-1 mb-2">
            <SceneTitleSection
                name={issue?.name}
                description={issue?.description}
                resourceType={{
                    type: 'error_tracking',
                }}
                isLoading={issueLoading}
                canEdit
                onNameChange={updateName}
                onDescriptionChange={updateDescription}
                renameDebounceMs={1000}
                actions={
                    <>
                        <ButtonPrimitive
                            onClick={() => {
                                if (!hasDiscussions) {
                                    posthog.updateEarlyAccessFeatureEnrollment('discussions', true)
                                }
                                openSidePanel(SidePanelTab.Discussion)
                            }}
                            tooltip="Comment"
                        >
                            <IconComment />
                            <span className="hidden @[200px]:block">Comment</span>
                        </ButtonPrimitive>

                        <ButtonPrimitive
                            onClick={() => {
                                if (issue) {
                                    void copyToClipboard(
                                        window.location.origin + urls.errorTrackingIssue(issue.id),
                                        'issue link'
                                    )
                                }
                            }}
                            tooltip="Share"
                            data-attr={`${RESOURCE_TYPE}-share`}
                        >
                            <IconShare />
                            <span className="hidden @[200px]:block">Share</span>
                        </ButtonPrimitive>
                        {hasIssueSplitting && (
                            <DropdownMenu>
                                <DropdownMenuTrigger asChild>
                                    <ButtonPrimitive iconOnly>
                                        <IconEllipsis />
                                    </ButtonPrimitive>
                                </DropdownMenuTrigger>

                                <DropdownMenuContent loop align="end">
                                    <DropdownMenuItem asChild>
                                        <ButtonPrimitive
                                            size="base"
                                            menuItem
                                            onClick={() =>
                                                router.actions.push(urls.errorTrackingIssueFingerprints(issueId))
                                            }
                                        >
                                            Split issue
                                        </ButtonPrimitive>
                                    </DropdownMenuItem>
                                </DropdownMenuContent>
                            </DropdownMenu>
                        )}
                    </>
                }
            />
            <div className="flex gap-x-2">
                <IssueStatusSelect status={issue?.status} disabled={issueLoading} onChange={updateStatus} />
                <IssueAssigneeSelect
                    assignee={issue?.assignee ?? null}
                    onChange={updateAssignee}
                    disabled={issueLoading || issue?.status != 'active'}
                />
            </div>
            <SceneDivider />
        </div>
    )
}

const IssueStatusSelect = ({
    status,
    disabled,
    onChange,
}: {
    status?: ErrorTrackingIssue['status']
    disabled: boolean
    onChange: (status: ErrorTrackingIssue['status']) => void
}): JSX.Element => {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <ButtonPrimitive variant="panel" disabled={disabled}>
                    {status ? (
                        <StatusIndicator status={status} withTooltip={true} />
                    ) : (
                        <LabelIndicator intent="muted" size="small" label="Loading" />
                    )}
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
        <AssigneeSelect assignee={assignee} onChange={onChange}>
            {(anyAssignee, isOpen) => (
                <ButtonPrimitive disabled={disabled} data-state={isOpen ? 'open' : 'closed'} variant="panel">
                    <div className="flex items-center">
                        <AssigneeIconDisplay assignee={anyAssignee} size="small" />
                        <AssigneeLabelDisplay assignee={anyAssignee} className="ml-1" size="small" />
                    </div>
                    {!disabled && <DropdownMenuOpenIndicator />}
                </ButtonPrimitive>
            )}
        </AssigneeSelect>
    )
}
