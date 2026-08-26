import type { CyclotronJobInputSchemaType } from '~/types'

import { stripSecretInputs } from './stripSecretInputs'

describe('stripSecretInputs', () => {
    const schema: CyclotronJobInputSchemaType[] = [
        { key: 'url', type: 'string', label: 'URL' },
        { key: 'auth_token', type: 'string', label: 'Auth token', secret: true },
    ]

    it.each([
        [
            'drops secret inputs and reports them',
            { url: { value: 'https://example.com' }, auth_token: { value: 'shh' } },
            schema,
            { url: { value: 'https://example.com' } },
            ['auth_token'],
        ],
        [
            'keeps everything when nothing is secret',
            { url: { value: 'https://example.com' } },
            [{ key: 'url', type: 'string', label: 'URL' }] as CyclotronJobInputSchemaType[],
            { url: { value: 'https://example.com' } },
            [],
        ],
        ['is a no-op without a schema', { url: { value: 'x' } }, undefined, { url: { value: 'x' } }, []],
    ])('%s', (_name, inputs, inputsSchema, expectedInputs, expectedStripped) => {
        const result = stripSecretInputs(inputs, inputsSchema)
        expect(result.inputs).toEqual(expectedInputs)
        expect(result.strippedKeys).toEqual(expectedStripped)
    })
})
