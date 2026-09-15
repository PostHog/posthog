import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

import { validateListAppToolCall } from '../../scripts/lib/validate-ui-app-tool-call'

describe('list app tool call validation', () => {
    const schema = { type: 'object', properties: { id: {}, include_details: {} }, required: ['id'] }
    const validate = (detail_args: string): void =>
        validateListAppToolCall('survey-list', { detail_tool: 'survey-get', detail_args }, schema)

    it('rejects the survey list argument mismatch against the committed tool schema snapshot', () => {
        const snapshot = JSON.parse(
            readFileSync(path.join(__dirname, '__snapshots__', 'tool-schemas', 'survey-get.json'), 'utf-8')
        )
        expect(() =>
            validateListAppToolCall(
                'survey-list',
                { detail_tool: 'survey-get', detail_args: '{ surveyId: item.id }' },
                snapshot
            )
        ).toThrow(/survey-list.*survey-get.*surveyId.*id/)
    })

    it.each(['{ id: item.id }', '{ "id": item.id, include_details: true }', '{ id }'])(
        'accepts explicit argument keys: %s',
        (args) => expect(() => validate(args)).not.toThrow()
    )

    it('rejects an unknown key even when all required arguments are supplied', () => {
        expect(() => validate('{ id: item.id, typo: true }')).toThrow(/Unknown arguments: typo/)
    })

    it('rejects a missing required argument', () => {
        expect(() => validate('{}')).toThrow(/Missing required arguments: id/)
    })

    it('rejects a tool without a schema snapshot', () => {
        expect(() =>
            validateListAppToolCall(
                'survey-list',
                { detail_tool: 'surveys-get', detail_args: '{ id: item.id }' },
                undefined
            )
        ).toThrow(/survey-list.*surveys-get.*no input schema snapshot/)
    })

    it.each(['{ ...item }', '{ [field]: item.id }', 'item', '{ id: item.id', '{ id: item.id }; throw new Error()'])(
        'rejects argument expressions whose keys cannot be checked: %s',
        (args) => expect(() => validate(args)).toThrow(/detail_args/)
    )

    it('does not execute argument expressions during generation', () => {
        expect(() => validate('{ id: (() => { throw new Error("executed") })() }')).not.toThrow()
    })
})
