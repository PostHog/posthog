import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import type { HogFlowApi } from 'products/workflows/frontend/generated/api.schemas'

import { broadcastWizardLogic } from './broadcastWizardLogic'

const LOCAL_AUDIENCE: AnyPropertyFilter[] = [
    { key: 'plan', value: ['pro'], operator: PropertyOperator.Exact, type: PropertyFilterType.Person },
]

function savedBroadcast(overrides: { name: string; subject: string; updatedAt: string }): HogFlowApi {
    return {
        id: 'broadcast-1',
        name: overrides.name,
        version: 1,
        status: 'draft',
        created_at: '2026-01-01T00:00:00Z',
        created_by: { id: 1, uuid: 'user-1', email: 'user@example.com', hedgehog_config: null },
        updated_at: overrides.updatedAt,
        trigger: { type: 'batch', filters: { properties: [] } },
        conversion: null,
        email_sending_rate_limit: null,
        actions: [
            {
                id: 'trigger_node',
                name: 'Trigger',
                type: 'trigger',
                config: { type: 'batch', filters: { properties: [] } },
            },
            {
                id: 'email_node',
                name: 'Email',
                type: 'function_email',
                config: { inputs: { email: { value: { subject: overrides.subject } } } },
            },
        ],
        abort_action: null,
        billable_action_types: [],
        schedules: [],
        user_access_level: 'editor',
        draft: null,
        draft_updated_at: null,
        action_redirects: null,
        email_sending_paused_at: null,
        email_sending_paused_reason: '',
        email_sending_paused_by: '',
        email_sending_pause_requires_support: false,
        email_sending_resumed_at: null,
    }
}

describe('broadcastWizardLogic', () => {
    let logic: ReturnType<typeof broadcastWizardLogic.build>
    let latest: HogFlowApi

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/:id/': () => [200, latest],
            },
            post: {
                '/api/projects/:team_id/hog_flows/user_blast_radius/': () => [200, { affected: 0, total: 0 }],
            },
        })
        initKeaTests()
        logic = broadcastWizardLogic({ id: 'new' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    test.each([
        { edited: 'only the email', latestName: 'Spring sale', expectedName: 'Spring sale, final' },
        { edited: 'the name too', latestName: 'Spring promo', expectedName: 'Spring promo' },
    ])(
        'an edit saved elsewhere that changed $edited keeps the unsaved local fields it did not change',
        async ({ latestName, expectedName }) => {
            const base = savedBroadcast({ name: 'Spring sale', subject: '', updatedAt: '2026-09-24T10:00:00Z' })
            latest = savedBroadcast({
                name: latestName,
                subject: 'Our spring sale starts today',
                updatedAt: '2026-09-24T10:00:05Z',
            })
            logic.actions.draftAutosaved(base)
            logic.actions.setName('Spring sale, final')
            logic.actions.setAudienceProperties(LOCAL_AUDIENCE)

            await expectLogic(logic, () => {
                logic.actions.resourceEdited({
                    notification_type: 'resource_edited',
                    team_id: 1,
                    resource_type: 'HogFlow',
                    resource_id: base.id,
                    updated_at: latest.updated_at,
                    actor_user_id: null,
                })
            })
                .toDispatchActions(['applyExternalEdit'])
                .toMatchValues({
                    broadcast: latest,
                    name: expectedName,
                    audienceProperties: LOCAL_AUDIENCE,
                    email: expect.objectContaining({ subject: 'Our spring sale starts today' }),
                })
        }
    )
})
