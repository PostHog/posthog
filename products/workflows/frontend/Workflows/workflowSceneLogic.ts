import { actions, kea, key, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { workflowSceneLogicType } from './workflowSceneLogicType'

export const WorkflowTabs = ['workflow', 'logs', 'metrics', 'history'] as const
export type WorkflowTab = (typeof WorkflowTabs)[number]

export interface WorkflowSceneLogicProps {
    id?: string
    tab?: WorkflowTab
    tabId?: string
}

export const workflowSceneLogic = kea<workflowSceneLogicType>([
    path(['products', 'workflows', 'frontend', 'workflowSceneLogic']),
    props({ id: 'new', tabId: 'default' } as WorkflowSceneLogicProps),
    key((props) => `workflow-scene-${props.id || 'new'}-${props.tabId}`),
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
    }),
    tabAwareActionToUrl(({ props, values }) => ({
        setCurrentTab: () => {
            return [
                urls.workflow(props.id || 'new', values.currentTab),
                router.values.searchParams,
                router.values.hashParams,
            ]
        },
    })),
    tabAwareUrlToAction(({ actions, values }) => ({
        '/workflows/:id/:tab': ({ tab }) => {
            if (tab !== values.currentTab) {
                actions.setCurrentTab(tab as WorkflowTab)
            }
        },
    })),
])
