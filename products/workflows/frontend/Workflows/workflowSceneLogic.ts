import { actions, kea, path, props, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { workflowSceneLogicType } from './workflowSceneLogicType'

export const WorkflowTabs = ['workflow', 'logs', 'metrics', 'history'] as const
export type WorkflowTab = (typeof WorkflowTabs)[number]

export interface WorkflowSceneLogicProps {
    id?: string
    tab?: WorkflowTab
}

export const workflowSceneLogic = kea<workflowSceneLogicType>([
    path(['products', 'workflows', 'frontend', 'workflowSceneLogic']),
    props({ id: 'new' } as WorkflowSceneLogicProps),
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
    actionToUrl(({ props, values }) => ({
        setCurrentTab: () => {
            return [
                urls.workflow(props.id || 'new', values.currentTab),
                router.values.searchParams,
                router.values.hashParams,
            ]
        },
    })),
    urlToAction(({ actions, values }) => ({
        '/workflows/:id/:tab': ({ tab }) => {
            if (tab !== values.currentTab) {
                actions.setCurrentTab(tab as WorkflowTab)
            }
        },
    })),
])
