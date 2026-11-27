import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { transactionalTemplatesLogic } from '../transactionalTemplatesLogic'
import { transactionalEmailMetricsLogic } from './transactionalEmailMetricsLogic'

const COUNTS = { sent: 3, delivered: 2, bounced: 1, complained: 0, opened: 1, clicked: 0, failed: 0 }
const EMAIL_ROWS = [
    { ...COUNTS, key: 'tpl-1', label: 'Order receipt', template_id: 'tpl-1', code_email_id: null },
    { ...COUNTS, key: 'flow-2', label: 'sign-in-code', template_id: null, code_email_id: 'code-1' },
    { ...COUNTS, key: 'flow-3', label: null, template_id: null, code_email_id: null },
]

const TEMPLATES = [{ id: 'tpl-1', name: 'Order receipt', transactional_hog_flow_id: 'flow-1' }]
const CODE_EMAILS = [{ id: 'code-9', key: 'password-changed', hog_flow_id: 'flow-9' }]

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
                '/api/projects/:team_id/messaging_templates/': [200, { count: TEMPLATES.length, results: TEMPLATES }],
                '/api/projects/:team_id/transactional_code_emails/': [200, CODE_EMAILS],
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

    it('offers the templates and every email sent from code, sent in the period or not', async () => {
        logic = transactionalEmailMetricsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(transactionalTemplatesLogic).toFinishAllListeners()

        expect(logic.values.resultsEmailOptions).toEqual([
            { title: 'Templates', options: [{ value: 'flow-1', label: 'Order receipt' }] },
            { title: 'Sent from code', options: [{ value: 'flow-9', label: 'password-changed' }] },
        ])
    })
})
