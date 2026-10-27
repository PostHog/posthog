import { parseCustomerioFiles } from './customerioImportFile'

const automation = { campaign: { id: 1, type: 'transactional' }, actions: [{ id: '1', type: 'email_action' }] }

describe('parseCustomerioFiles', () => {
    test.each([
        ['one automation per file', [JSON.stringify(automation), JSON.stringify(automation)], 2],
        ['a list of automations', [JSON.stringify([automation, automation])], 2],
        ['the import request shape', [JSON.stringify({ campaigns: [automation], snippets: { footer: 'x' } })], 1],
        ['a file with no automation', [JSON.stringify({ campaigns: 'nope' })], 0],
    ])('reads %s', (_name, files, count) => {
        expect(parseCustomerioFiles(files).campaigns).toHaveLength(count)
    })

    it('attaches loose templates only to automations that use them, next to keyed ones', () => {
        const template = { template: { id: 11, subject: 'Hi', body: '<p>Hi</p>' } }
        const user = {
            campaign: { id: 2 },
            actions: [{ id: '5', type: 'email_action', template_id: 11 }],
            templates: { 12: { subject: 'Kept', body: '<p>Kept</p>' } },
        }
        const parsed = parseCustomerioFiles([
            JSON.stringify(automation),
            JSON.stringify(user),
            JSON.stringify(template),
        ])

        expect(parsed.campaigns[0].templates).toEqual([])
        expect(parsed.campaigns[1].templates).toEqual([
            { id: '12', subject: 'Kept', body: '<p>Kept</p>' },
            template.template,
        ])
    })

    it('rejects a file that is not JSON', () => {
        expect(() => parseCustomerioFiles(['{nope'])).toThrow('One of the files is not valid JSON.')
    })
})
