import { afterMount, kea, key, path, props } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import type { campaignLogicType } from './campaignLogicType'
import type { HogFlow } from './Workflows/types'

export interface CampaignLogicProps {
    id?: string
}

const DEFAULT_WORKFLOW: HogFlow = {
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

export const campaignLogic = kea<campaignLogicType>([
    path(['products', 'messaging', 'frontend', 'campaignLogic']),
    props({ id: 'new' } as CampaignLogicProps),
    key((props) => props.id || 'new'),
    forms(() => ({
        campaign: {
            defaults: {
                ...DEFAULT_WORKFLOW,
                triggerEvents: {},
                hasConversionGoal: false,
                conversionProperties: [],
                conversionWindowMinutes: 7 * 24 * 60, // 7 days in minutes
                collectionMethod: 'exit_only_at_end',
            },
            errors: ({ name }) => ({
                name: !name ? 'Please enter a name' : undefined,
            }),
            submit: async (values) => {
                // TODO: Add API call to save campaign
                alert(`Submitting campaign: ${JSON.stringify(values)}`)
            },
        },
    })),
    loaders(({ props }) => ({
        campaign: [
            { ...DEFAULT_WORKFLOW } as HogFlow,
            {
                loadCampaign: async () => {
                    if (!props.id || props.id === 'new') {
                        return { ...DEFAULT_WORKFLOW }
                    }

                    // TODO: Add GET /hog_flows/{id} API call
                    return { ...DEFAULT_WORKFLOW }
                },
            },
        ],
    })),
    afterMount(({ actions, props }) => {
        if (props.id && props.id !== 'new') {
            actions.loadCampaign()
        }
    }),
])
