import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { router } from 'node_modules/kea-router/lib/router'
import { urls } from 'scenes/urls'

import type { campaignLogicType } from './campaignLogicType'
import type { HogFlow, HogFlowAction, HogFlowEdge } from './Workflows/types'
import { MessageTemplate } from '../TemplateLibrary/messageTemplatesLogic'

export interface CampaignLogicProps {
    id?: string
}

const NEW_CAMPAIGN: HogFlow = {
    id: 'new',
    name: 'Untitled campaign',
    edges: [],
    actions: [],
    trigger: { type: 'event' },
    trigger_masking: { ttl: 0, hash: '', threshold: 0 },
    conversion: { window_minutes: 0, filters: [] },
    exit_condition: 'exit_on_conversion',
    version: 1,
    status: 'draft',
    team_id: 0,
}

export type OnWorkflowChange = ({ actions, edges }: { actions: HogFlowAction[]; edges: HogFlowEdge[] }) => void

export const campaignLogic = kea<campaignLogicType>([
    path(['products', 'messaging', 'frontend', 'campaignLogic']),
    props({ id: 'new' } as CampaignLogicProps),
    key((props) => props.id || 'new'),
    actions({
        setCampaign: (campaign: HogFlow) => ({ campaign }),
        setOriginalCampaign: (campaign: HogFlow) => ({ campaign }),
    }),
    loaders(({ props }) => ({
        campaign: {
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
    })),
    forms(({ actions }) => ({
        campaign: {
            defaults: {
                ...NEW_CAMPAIGN,
                triggerEvents: {},
                hasConversionGoal: false,
                conversionProperties: [],
                conversionWindowMinutes: 7 * 24 * 60, // 7 days in minutes
                collectionMethod: 'exit_only_at_end',
            },
            submit: async (values) => {
                actions.saveCampaign(values)
            },
        },
    })),
    reducers({
        campaign: [
            { ...NEW_CAMPAIGN } as HogFlow,
            {
                setCampaign: (_, { campaign }) => campaign,
            },
        ],
        originalCampaign: [
            { ...NEW_CAMPAIGN } as HogFlow,
            {
                setOriginalCampaign: (_, { campaign }) => campaign,
                loadCampaignSuccess: (_, { campaign }) => {
                    return campaign
                },
            },
        ],
    }),
    listeners(({ actions }) => ({
        saveCampaignSuccess: async ({ campaign }) => {
            lemonToast.success('Campaign saved')
            campaign.id && router.actions.replace(urls.messagingCampaign(campaign.id))
            actions.resetCampaign(campaign)
            actions.setOriginalCampaign(campaign)
        },
    })),
    afterMount(({ actions, props }) => {
        if (props.id && props.id !== 'new') {
            actions.loadCampaign()
        }
    }),
])
