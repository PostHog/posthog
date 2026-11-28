import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { SlackScoutChannelSourceApi } from 'products/signals/frontend/generated/api.schemas'

import { slackChannelScoutLogic } from './slackChannelScoutLogic'

const SOURCES: SlackScoutChannelSourceApi[] = [
    {
        id: 'source-a',
        label: 'support',
        channels: [
            { id: 'C01', name: 'bugs', table_name: 'slack.c01' },
            { id: 'C02', name: 'feedback', table_name: 'slack.c02' },
            { id: 'C03', name: 'random', table_name: 'slack.c03' },
        ],
    },
    {
        id: 'source-b',
        label: 'Connected Mar 5, 2026',
        channels: [
            { id: 'C01', name: 'bugs', table_name: 'slack.b_c01' },
            { id: 'C02', name: 'feedback', table_name: null },
        ],
    },
]

describe('slackChannelScoutLogic', () => {
    let logic: ReturnType<typeof slackChannelScoutLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/signals/slack_channel_scouts/channels/': { sources: SOURCES },
                '/api/projects/:team_id/signals/scout/configs/': [],
            },
        })
        initKeaTests()
        logic = slackChannelScoutLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('keeps only the picked channels that the new source has synced when the source changes', async () => {
        logic.actions.openSlackScoutModal()
        logic.actions.setSlackScoutValue('channel_ids', ['C01', 'C02', 'C03'])

        logic.actions.pickSlackScoutSource('source-b')

        expect(logic.values.slackScout).toMatchObject({ source_id: 'source-b', channel_ids: ['C01'] })
    })
})
