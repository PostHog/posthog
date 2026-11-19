import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconArchive, IconCopy, IconScreen } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { SceneTags } from 'lib/components/Scenes/SceneTags'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import {
    ScenePanel,
    ScenePanelActionsSection,
    ScenePanelDivider,
    ScenePanelInfoSection,
} from '~/layout/scenes/SceneLayout'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { workflowSuggestionsAvailabilityLogic } from './suggestions/workflowSuggestionsAvailabilityLogic'
import { WorkflowSuggestionsPanelToggle } from './suggestions/WorkflowSuggestionsPanelToggle'
import { workflowTemplateLogic } from './templates/workflowTemplateLogic'
import { canEditWorkflow } from './workflowAccess'
import { workflowLogic } from './workflowLogic'
import { WorkflowSceneLogicProps } from './workflowSceneLogic'

export function WorkflowScenePanel(props: WorkflowSceneLogicProps): JSX.Element {
    const { workflow, workflowUserAccessLevel } = useValues(workflowLogic)
    const { duplicate, archiveWorkflow, setWorkflowValue } = useActions(workflowLogic)
    const { searchParams } = useValues(router)
    const editTemplateId = searchParams.editTemplateId as string | undefined
    const { showSaveAsTemplateModal } = useActions(workflowTemplateLogic({ ...props, editTemplateId }))
    const { suggestionsAvailable } = useValues(workflowSuggestionsAvailabilityLogic)
    const canEdit = canEditWorkflow(workflow, workflowUserAccessLevel)

    return (
        <ScenePanel>
            <ScenePanelInfoSection>
                <SceneTags
                    onSave={(tags) => setWorkflowValue('tags', tags)}
                    canEdit={canEdit}
                    tags={workflow.tags ?? []}
                    dataAttrKey="workflow"
                />
            </ScenePanelInfoSection>
            <ScenePanelDivider />
            {suggestionsAvailable && (
                <>
                    <ScenePanelActionsSection>
                        <WorkflowSuggestionsPanelToggle id={props.id!} />
                    </ScenePanelActionsSection>
                    <ScenePanelDivider />
                </>
            )}
            <ScenePanelActionsSection>
                <ButtonPrimitive menuItem onClick={() => duplicate()} data-attr="workflow-duplicate-btn">
                    <IconCopy />
                    Duplicate
                </ButtonPrimitive>
                <ButtonPrimitive menuItem onClick={showSaveAsTemplateModal} data-attr="workflow-save-as-template-btn">
                    <IconScreen />
                    Save as template
                </ButtonPrimitive>
            </ScenePanelActionsSection>
            <ScenePanelDivider />
            <ScenePanelActionsSection>
                <AccessControlAction
                    resourceType={AccessControlResourceType.Workflow}
                    minAccessLevel={AccessControlLevel.Editor}
                    userAccessLevel={workflowUserAccessLevel ?? undefined}
                >
                    {({ disabledReason }) => (
                        <ButtonPrimitive
                            menuItem
                            onClick={() => archiveWorkflow(workflow)}
                            variant="danger"
                            data-attr="workflow-archive-btn"
                            disabled={!!disabledReason}
                            tooltip={disabledReason ?? undefined}
                        >
                            <IconArchive />
                            Archive
                        </ButtonPrimitive>
                    )}
                </AccessControlAction>
            </ScenePanelActionsSection>
        </ScenePanel>
    )
}
