import { actions, kea, key, path, props, reducers, selectors } from 'kea'
import { urlToAction } from 'kea-router'

import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { ActivityScope, Breadcrumb } from '~/types'

import type { workflowSceneLogicType } from './workflowSceneLogicType'

export const WorkflowTabs = ['workflow', 'logs', 'invocations', 'metrics', 'assets', 'history'] as const
export type WorkflowTab = (typeof WorkflowTabs)[number]

export interface WorkflowSceneLogicProps {
    id?: string
    tab?: WorkflowTab
}

export const workflowSceneLogic = kea<workflowSceneLogicType>([
    path(['products', 'workflows', 'frontend', 'workflowSceneLogic']),
    props({ id: 'new' } as WorkflowSceneLogicProps),
    key((props) => `workflow-scene-${props.id || 'new'}`),
    actions({
        setCurrentTab: (tab: WorkflowTab) => ({ tab }),
    }),
    reducers({
        currentTab: [
            'workflow' as WorkflowTab,
            {
                setCurrentTab: (_, { tab }) => tab,
            },
        ],
    }),
    selectors({
        breadcrumbs: [
            () => [(_, props) => props.id as WorkflowSceneLogicProps['id']],
            (id): Breadcrumb[] => {
                return [
                    {
                        key: [Scene.Workflows, 'workflows'],
                        name: 'Workflows',
                        path: urls.workflows('workflows'),
                        iconType: 'workflows',
                    },
                    {
                        key: Scene.Workflow,
                        name: id == 'new' ? 'New workflow' : 'Manage workflow',
                        iconType: 'workflows',
                    },
                ]
            },
        ],
        // Drives the side panel: surfaces the Access control (and Activity) tab for a saved workflow.
        // Must live on the scene logic — sidePanelContextLogic reads SIDE_PANEL_CONTEXT_KEY off the
        // scene's registered logic, not workflowLogic.
        [SIDE_PANEL_CONTEXT_KEY]: [
            () => [(_, props) => props.id as WorkflowSceneLogicProps['id']],
            (id): SidePanelSceneContext | null =>
                id && id !== 'new'
                    ? {
                          activity_scope: ActivityScope.HOG_FLOW,
                          activity_item_id: id,
                          access_control_resource: 'hog_flow',
                          access_control_resource_id: id,
                      }
                    : null,
        ],
    }),
    urlToAction(({ actions, values }) => ({
        '/workflows/:id/:tab': ({ tab }) => {
            if (tab !== values.currentTab) {
                actions.setCurrentTab(tab as WorkflowTab)
            }
        },
    })),
])
