import { useActions } from 'kea'

import { IconDownload, IconPlus } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { MessagingTabSceneActions } from './MessagingTabSceneActions'
import { customerioImportLogic } from './Workflows/import/customerioImportLogic'
import type { WorkflowsSceneTab } from './WorkflowsScene'

const RESOURCE_TYPE = 'workflows'

interface WorkflowsSceneMenuBarProps {
    currentTab: Exclude<WorkflowsSceneTab, 'onboarding'>
    onNewWorkflow: () => void
}

export function WorkflowsSceneMenuBar(props: WorkflowsSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <WorkflowsSceneMenuBarInner {...props} /> : null
}

function WorkflowsSceneMenuBarInner({ currentTab, onNewWorkflow }: WorkflowsSceneMenuBarProps): JSX.Element {
    const { openImportModal } = useActions(customerioImportLogic)
    const accessDisabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.Workflow, AccessControlLevel.Editor) ?? undefined

    if (currentTab !== 'workflows' && currentTab !== 'templates' && currentTab !== 'calendar') {
        return (
            <MessagingTabSceneActions
                tab={currentTab}
                channelsUrl={urls.workflows('channels')}
                actions={[]}
                dataAttrKey={RESOURCE_TYPE}
            />
        )
    }

    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-new-workflow`,
            label: 'New workflow',
            icon: <IconPlus />,
            opensFloatingUi: true,
            disabledReason: accessDisabledReason,
            onSelect: onNewWorkflow,
            pinned: { order: 2, variant: 'primary', dataAttr: 'new-workflow' },
        },
        {
            group: 'file',
            section: 'import',
            id: `${RESOURCE_TYPE}-menubar-import-customerio`,
            label: 'Import from Customer.io',
            icon: <IconDownload />,
            opensFloatingUi: true,
            disabledReason: accessDisabledReason,
            onSelect: openImportModal,
            pinned: { order: 1, variant: 'secondary', dataAttr: 'workflows-import-customerio' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
