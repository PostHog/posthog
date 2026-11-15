import { transactionalEmailSendsUrl, transactionalEmailUrl } from './transactionalEmailUrl'

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
