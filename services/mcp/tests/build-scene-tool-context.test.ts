import { describe, expect, it } from 'vitest'

import { resolveToolSummaries } from '../scripts/build-scene-tool-context'

describe('build scene tool context', () => {
    it('selects requested tools in configured order', () => {
        expect(
            resolveToolSummaries(
                {
                    first: { enabled: true },
                    second: { enabled: true },
                    omitted: { enabled: true },
                },
                {
                    first: { description: 'First tool' },
                    second: { description: 'Second tool' },
                    omitted: { description: 'Omitted tool' },
                },
                { includeTools: ['second', 'first'] },
                'tools.yaml'
            )
        ).toEqual([
            { name: 'second', description: 'Second tool' },
            { name: 'first', description: 'First tool' },
        ])
    })

    it('rejects requested tools that are disabled or absent from the YAML source', () => {
        const definitions = {
            disabled: { description: 'Disabled tool' },
            missing: { description: 'Missing tool' },
        }

        expect(() =>
            resolveToolSummaries(
                { disabled: { enabled: false } },
                definitions,
                { includeTools: ['disabled'] },
                'tools.yaml'
            )
        ).toThrow('tool "disabled" is not enabled in tools.yaml')
        expect(() => resolveToolSummaries({}, definitions, { includeTools: ['missing'] }, 'tools.yaml')).toThrow(
            'tool "missing" is not defined in tools.yaml'
        )
    })

    it('rejects requested tools without a generated definition', () => {
        expect(() =>
            resolveToolSummaries({ requested: { enabled: true } }, {}, { includeTools: ['requested'] }, 'tools.yaml')
        ).toThrow('tool "requested" has no description in tool-definitions-all.json')
    })
})
