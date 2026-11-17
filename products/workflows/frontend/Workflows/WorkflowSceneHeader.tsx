import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { SaveAsTemplateModal } from './templates/SaveAsTemplateModal'
import { canEditWorkflow } from './workflowAccess'
import { WorkflowActions } from './WorkflowActions'
import { workflowBackTo } from './workflowBackTo'
import { workflowLogic } from './workflowLogic'
import { WorkflowSceneLogicProps } from './workflowSceneLogic'
import { WorkflowSceneMenuBar } from './WorkflowSceneMenuBar'
import { WorkflowScenePanel } from './WorkflowScenePanel'

export const WorkflowSceneHeader = (props: WorkflowSceneLogicProps = {}): JSX.Element => {
    const { workflow, workflowLoading, workflowUserAccessLevel } = useValues(workflowLogic)
    const { setWorkflowValue } = useActions(workflowLogic)
    const { searchParams } = useValues(router)
    const editTemplateId = searchParams.editTemplateId as string | undefined

    const isSavedWorkflow = props.id && props.id !== 'new'
    const { featureFlags } = useValues(featureFlagLogic)
    const sceneMenuBarEnabled = !!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]
    const canEdit = canEditWorkflow(workflow, workflowUserAccessLevel)

    return (
        <>
            <SaveAsTemplateModal {...props} editTemplateId={editTemplateId} />
            {sceneMenuBarEnabled && isSavedWorkflow && <WorkflowSceneMenuBar {...props} id={props.id!} />}
            <SceneTitleSection
                name={workflow?.name}
                description={workflow?.description}
                resourceType={{ type: 'workflows' }}
                canEdit={canEdit}
                onNameChange={(name) => setWorkflowValue('name', name)}
                onDescriptionChange={(description) => setWorkflowValue('description', description)}
                isLoading={workflowLoading && !workflow}
                renameDebounceMs={200}
                hideProductSetupButton
                forceBackTo={workflowBackTo(workflow, props.id)}
                actions={
                    <>
                        <WorkflowActions {...props} />
                        {isSavedWorkflow && <WorkflowScenePanel {...props} />}
                    </>
                }
            />
        </>
    )
}
