import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { router } from 'node_modules/kea-router/lib/router'
import { urls } from 'scenes/urls'

import type { campaignLogicType } from './campaignLogicType'
import { campaignSceneLogic } from './campaignSceneLogic'
import type { HogFlow, HogFlowAction, HogFlowEdge } from './Workflows/types'

export interface CampaignLogicProps {
    id?: string
}

const NEW_CAMPAIGN: HogFlow = {
    id: 'new',
    name: '',
    edges: [],
    actions: [],
    trigger: { type: 'event' },
    trigger_masking: { ttl: 0, hash: '', threshold: 0 },
    conversion: { window_minutes: 0, filters: [] },
    exit_condition: 'exit_only_at_end',
    version: 1,
    status: 'draft',
    team_id: -1,
}

export type OnWorkflowChange = ({ actions, edges }: { actions: HogFlowAction[]; edges: HogFlowEdge[] }) => void

export const campaignLogic = kea<campaignLogicType>([
    path(['products', 'messaging', 'frontend', 'Campaigns', 'campaignLogic']),
    props({ id: 'new' } as CampaignLogicProps),
    key((props) => props.id || 'new'),
    actions({
        setOriginalCampaign: (campaign: HogFlow) => ({ campaign }),
    }),
    loaders(() => ({
        campaign: {
            loadCampaign: async () => {
                return { ...NEW_CAMPAIGN }
            },
            saveCampaign: async () => {
                return { ...NEW_CAMPAIGN }
            },
        },
    })),
    forms(({ actions }) => ({
        campaign: {
            defaults: { ...NEW_CAMPAIGN },
            submit: async () => {
                actions.saveCampaign()
            },
        },
    })),
    reducers({
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
            campaign.id &&
                router.actions.replace(
                    urls.messagingCampaign(campaign.id, campaignSceneLogic.findMounted()?.values.currentTab)
                )
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
