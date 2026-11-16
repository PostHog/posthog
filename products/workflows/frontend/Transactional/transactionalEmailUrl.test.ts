import {
    transactionalEmailSendsUrl,
    transactionalEmailStatsRowUrl,
    transactionalEmailUrl,
} from './transactionalEmailUrl'

describe('transactionalEmailUrl', () => {
    test.each([
        [
            'a send from code opens its code email',
            { code_email_id: 'code-1', template_id: null },
            '/transactional/code-emails/code-1',
        ],
        [
            'a template send opens its template',
            { code_email_id: null, template_id: 'tpl-1' },
            '/transactional/library/templates/tpl-1',
        ],
        ['a send of a deleted email opens nothing', { code_email_id: null, template_id: null }, null],
    ])('%s', (_name, email, expected) => {
        expect(transactionalEmailUrl(email)).toBe(expected)
    })

    test.each([
        [
            'carries the status and dates back to the Sends tab',
            { status: 'bounced', date_from: '-3d', date_to: '2026-03-14' },
            '/transactional/code-emails/code-1?tab=sends&status=bounced&date_from=-3d&date_to=2026-03-14',
        ],
        [
            "leaves out what the email's Sends tab does not filter on",
            { search: 'ada@example.com', email: 'flow-2', page: '3' },
            '/transactional/code-emails/code-1?tab=sends',
        ],
    ])('%s', (_name, searchParams, expected) => {
        expect(transactionalEmailSendsUrl({ code_email_id: 'code-1', template_id: null }, searchParams)).toBe(expected)
    })
})

describe('transactionalEmailStatsRowUrl', () => {
    const counts = { sent: 3, delivered: 2, bounced: 1, complained: 0, opened: 1, clicked: 0, failed: 0 }

    test.each([
        [
            'a code email row opens its code email',
            { key: 'order-shipped', label: 'order-shipped', code_email_id: 'code-1', template_id: null },
            '/transactional/code-emails/code-1',
        ],
        [
            'a row whose email is gone opens nothing',
            { key: 'welcome', label: 'welcome', code_email_id: null, template_id: null },
            null,
        ],
        [
            'a template row from a Django pod of the release before still opens its template',
            { key: 'tpl-1', label: 'Order receipt' },
            '/transactional/library/templates/tpl-1',
        ],
        [
            'a row without a template from a Django pod of the release before opens nothing',
            { key: 'flow-1', label: '' },
            null,
        ],
    ])('%s', (_name, row, expected) => {
        expect(transactionalEmailStatsRowUrl({ ...counts, ...row })).toBe(expected)
    })
})
