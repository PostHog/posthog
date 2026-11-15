import { transactionalEmailUrl } from './transactionalEmailUrl'

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
})
