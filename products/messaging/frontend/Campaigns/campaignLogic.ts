import { LemonDialog } from '@posthog/lemon-ui'
import { actions, afterMount, kea, key, listeners, path, props, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { urls } from 'scenes/urls'

import type { campaignLogicType } from './campaignLogicType'
import { campaignSceneLogic } from './campaignSceneLogic'
import { type HogFlow, type HogFlowAction, type HogFlowEdge } from './hogflows/types'

export interface CampaignLogicProps {
    id?: string
}

const NEW_CAMPAIGN: HogFlow = {
    id: 'new',
    name: '',
    actions: [
        {
            id: 'trigger_node',
            type: 'trigger',
            name: 'Trigger',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: {
                type: 'event',
                filters: {},
            },
        },
        {
            id: 'exit_node',
            type: 'exit',
            name: 'Exit',
            config: {
                reason: 'Default exit',
            },
            description: '',
            created_at: 0,
            updated_at: 0,
        },
    ],
    edges: [
        {
            from: 'trigger_node',
            to: 'exit_node',
            type: 'continue',
        },
    ],
    trigger: {
        type: 'event',
        filters: {
            events: [],
            actions: [],
        },
    },
    trigger_masking: { ttl: 0, hash: '', threshold: 0 },
    conversion: { window_minutes: 0, filters: [] },
    exit_condition: 'exit_only_at_end',
    version: 1,
    status: 'draft',
    team_id: -1,
}

export const campaignLogic = kea<campaignLogicType>([
    path(['products', 'messaging', 'frontend', 'Campaigns', 'campaignLogic']),
    props({ id: 'new' } as CampaignLogicProps),
    key((props) => props.id || 'new'),
    actions({
        setCampaignActionConfig: (actionId: string, config: Partial<HogFlowAction['config']>) => ({ actionId, config }),
        setCampaignAction: (actionId: string, action: HogFlowAction) => ({ actionId, action }),
        setCampaignActionEdges: (actionId: string, edges: HogFlow['edges']) => ({ actionId, edges }),
        // NOTE: This is a wrapper for setCampaignValues, to get around some weird typegen issues
        setCampaignInfo: (campaign: Partial<HogFlow>) => ({ campaign }),
        discardChanges: true,
    }),
    loaders(({ props }) => ({
        originalCampaign: [
            null as HogFlow | null,
            {
                loadCampaign: async () => {
                    if (!props.id || props.id === 'new') {
                        return { ...NEW_CAMPAIGN }
                    }

                    return api.hogFlows.getHogFlow(props.id)
                },
                saveCampaign: async (updates: Partial<HogFlow>) => {
                    if (!props.id || props.id === 'new') {
                        return api.hogFlows.createHogFlow(updates)
                    }

                    return api.hogFlows.updateHogFlow(props.id, updates)
                },
            },
        ],
    })),
    forms(({ actions }) => ({
        campaign: {
            defaults: NEW_CAMPAIGN,
            errors: ({ name, trigger }) => {
                return {
                    name: name.length === 0 ? 'Name is required' : undefined,
                    trigger: {
                        filters:
                            trigger.filters.events.length === 0 && trigger.filters.actions.length === 0
                                ? 'At least one event or action is required'
                                : undefined,
                    },
                }
            },
            submit: async (values) => {
                if (!values) {
                    return
                }

                actions.saveCampaign(values)
            },
            options: {
                showErrorsOnTouch: true,
            },
        },
    })),
    selectors({
        logicProps: [() => [(_, props) => props], (props): CampaignLogicProps => props],
        campaignLoading: [(s) => [s.originalCampaignLoading], (originalCampaignLoading) => originalCampaignLoading],
        edgesByActionId: [
            (s) => [s.campaign],
            (campaign): Record<string, HogFlowEdge[]> => {
                return campaign.edges.reduce((acc, edge) => {
                    if (!acc[edge.from]) {
                        acc[edge.from] = []
                    }
                    acc[edge.from].push(edge)

                    if (!acc[edge.to]) {
                        acc[edge.to] = []
                    }
                    acc[edge.to].push(edge)

                    return acc
                }, {} as Record<string, HogFlowEdge[]>)
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        loadCampaignSuccess: async ({ originalCampaign }) => {
            actions.resetCampaign(originalCampaign)
        },
        saveCampaignSuccess: async ({ originalCampaign }) => {
            lemonToast.success('Campaign saved')
            originalCampaign.id &&
                router.actions.replace(
                    urls.messagingCampaign(originalCampaign.id, campaignSceneLogic.findMounted()?.values.currentTab)
                )
            actions.resetCampaign(originalCampaign)
        },
        discardChanges: () => {
            if (!values.originalCampaign) {
                return
            }

            LemonDialog.open({
                title: 'Discard changes',
                description: 'Are you sure?',
                primaryButton: {
                    children: 'Discard',
                    onClick: () => actions.resetCampaign(values.originalCampaign ?? NEW_CAMPAIGN),
                },
                secondaryButton: {
                    children: 'Cancel',
                },
            })
        },
        setCampaignInfo: async ({ campaign }) => {
            actions.setCampaignValues(campaign)
        },
        setCampaignActionConfig: async ({ actionId, config }) => {
            const action = values.campaign.actions.find((action) => action.id === actionId)
            if (!action) {
                return
            }

            action.config = { ...action.config, ...config }
            actions.setCampaignValues({ actions: [...values.campaign.actions] })
        },
        setCampaignAction: async ({ actionId, action }) => {
            const newActions = values.campaign.actions.map((a) => (a.id === actionId ? action : a))
            actions.setCampaignValues({ actions: newActions })
        },
        setCampaignActionEdges: async ({ actionId, edges }) => {
            // Helper method - Replaces all edges related to the action with the new edges
            const actionEdges = values.edgesByActionId[actionId] ?? []
            const newEdges = values.campaign.edges.filter((e) => !actionEdges.includes(e))

            actions.setCampaignValues({ edges: [...newEdges, ...edges] })
        },
    })),
    afterMount(({ actions, props }) => {
        if (props.id && props.id !== 'new') {
            actions.loadCampaign()
        }
    }),
])
