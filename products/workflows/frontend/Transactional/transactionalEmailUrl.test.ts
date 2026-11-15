import { transactionalEmailSendsUrl, transactionalEmailUrl } from './transactionalEmailUrl'

describe('transactionalEmailUrl', () => {
    test.each([
        [
            'a send from code opens its code email',
            { codeEmailId: 'code-1', templateId: null },
            '/transactional/code-emails/code-1',
        ],
        [
            'a template send opens its template',
            { codeEmailId: null, templateId: 'tpl-1' },
            '/transactional/library/templates/tpl-1',
        ],
        ['a send of a deleted email opens nothing', { codeEmailId: null, templateId: null }, null],
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
        expect(transactionalEmailSendsUrl({ codeEmailId: 'code-1', templateId: null }, searchParams)).toBe(expected)
    })
})
