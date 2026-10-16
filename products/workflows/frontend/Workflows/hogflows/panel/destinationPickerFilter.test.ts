import { HogFunctionTemplateType } from '~/types'

import { destinationPickerFilter } from './destinationPickerFilter'

const TOP_LEVEL_ID = 'template-already-a-button'

const template = (overrides: Partial<HogFunctionTemplateType>): HogFunctionTemplateType =>
    ({
        id: 'template-example',
        type: 'destination',
        name: 'Example',
        status: 'stable',
        free: false,
        code: '',
        code_language: 'hog',
        inputs_schema: [],
        ...overrides,
    }) as HogFunctionTemplateType

describe('destinationPickerFilter', () => {
    const isOffered = destinationPickerFilter([TOP_LEVEL_ID])

    it.each([
        [
            'offers a destination that declares a secret input',
            template({
                inputs_schema: [
                    { key: 'url', type: 'string', label: 'URL', secret: false },
                    { key: 'api_key', type: 'string', label: 'API key', secret: true },
                ],
            }),
            true,
        ],
        ['offers a destination with no secret inputs', template({}), true],
        [
            'leaves out a mapping destination that declares a secret input',
            template({
                inputs_schema: [{ key: 'api_token', type: 'string', label: 'API token', secret: true }],
                mapping_templates: [{ name: 'Conversion', include_by_default: true, inputs_schema: [] }],
            }),
            false,
        ],
        ['leaves out a hidden destination', template({ status: 'hidden' }), false],
        ['leaves out a destination that is coming soon', template({ status: 'coming_soon' }), false],
        ['leaves out a destination that already has its own button', template({ id: TOP_LEVEL_ID }), false],
        ['leaves out a template that is not a destination', template({ type: 'source_webhook' }), false],
    ])('%s', (_name, candidate, expected) => {
        expect(isOffered(candidate)).toBe(expected)
    })
})
