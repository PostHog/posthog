import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { transactionalEmailMetricsLogic } from './transactionalEmailMetricsLogic'

const COUNTS = { sent: 3, delivered: 2, bounced: 1, complained: 0, opened: 1, clicked: 0, failed: 0 }
const EMAIL_ROWS = [
    { ...COUNTS, key: 'tpl-1', label: 'Order receipt', template_id: 'tpl-1', code_email_id: null },
    { ...COUNTS, key: 'flow-2', label: 'sign-in-code', template_id: null, code_email_id: 'code-1' },
    { ...COUNTS, key: 'flow-3', label: null, template_id: null, code_email_id: null },
]

describe('transactionalEmailMetricsLogic', () => {
    let logic: ReturnType<typeof transactionalEmailMetricsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/transactional_email_log/stats/': ({ request }) => [
                    200,
                    { results: new URL(request.url).searchParams.get('group_by') === 'template' ? EMAIL_ROWS : [] },
                ],
                '/api/projects/:team_id/transactional_email_log/stats_over_time/': [200, { results: [] }],
            },
        })
        initKeaTests()
    })

    afterEach(() => logic.unmount())

    it.each([
        [
            'without the flag, as before',
            undefined,
            {
                'tpl-1': urls.transactionalTemplate('tpl-1'),
                'flow-2': urls.transactionalTemplate('flow-2'),
                'flow-3': null,
            },
        ],
        [
            'with the flag off, as before',
            false,
            {
                'tpl-1': urls.transactionalTemplate('tpl-1'),
                'flow-2': urls.transactionalTemplate('flow-2'),
                'flow-3': null,
            },
        ],
        [
            'with the flag on, to its own email',
            true,
            {
                'tpl-1': urls.transactionalTemplate('tpl-1'),
                'flow-2': urls.transactionalCodeEmail('code-1'),
                'flow-3': null,
            },
        ],
    ])('links each email row %s', async (_name, sendLinks, links) => {
        if (sendLinks !== undefined) {
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags(sendLinks ? [FEATURE_FLAGS.WORKFLOWS_EMAIL_SEND_LINKS] : [], {
                [FEATURE_FLAGS.WORKFLOWS_EMAIL_SEND_LINKS]: sendLinks,
            })
        }
        logic = transactionalEmailMetricsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.templateStatsLinks).toEqual(links)
    })
})
