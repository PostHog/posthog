import { transactionalEmailUrl } from './transactionalEmailUrl'

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
})
