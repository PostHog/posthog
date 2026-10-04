import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { stringify } from 'yaml'

import { parseToolDefinition } from '../../scripts/lib/definitions.mjs'

describe('parseToolDefinition', () => {
    let directory: string
    let filePath: string

    beforeEach(() => {
        directory = fs.mkdtempSync(path.join(os.tmpdir(), 'mcp-definitions-'))
        filePath = path.join(directory, 'tools.yaml')
    })

    afterEach(() => {
        fs.rmSync(directory, { recursive: true, force: true })
    })

    it.each([
        { first: undefined, second: ['kind'] },
        { first: ['kind'], second: undefined },
        { first: ['kind'], second: ['name'] },
        { first: ['config.secret'], second: [] },
    ])('rejects conflicting exclusions $first and $second on a shared operation', ({ first, second }) => {
        fs.writeFileSync(
            filePath,
            stringify({
                tools: {
                    'things-create': { operation: 'things_create', enabled: true, exclude_params: first },
                    'things-email-create': { operation: 'things_create', enabled: true, exclude_params: second },
                },
            })
        )

        expect(() => parseToolDefinition(filePath)).toThrow(
            `Tools on "things_create" in ${filePath} exclude different params. Give them the same exclude_params.`
        )
    })

    it.each([
        { first: undefined, second: [], expected: [] },
        { first: ['kind'], second: ['kind'], expected: ['kind'] },
        { first: ['name', 'kind', 'kind'], second: ['kind', 'name'], expected: ['kind', 'name'] },
    ])('accepts equivalent exclusions $first and $second', ({ first, second, expected }) => {
        fs.writeFileSync(
            filePath,
            stringify({
                tools: {
                    'things-create': { operation: 'things_create', enabled: true, exclude_params: first },
                    'things-email-create': { operation: 'things_create', enabled: true, exclude_params: second },
                },
            })
        )

        expect(parseToolDefinition(filePath)).toEqual({
            operationIds: new Set(['things_create']),
            schemaExclusions: new Map([['things_create', expected]]),
        })
    })

    it('ignores disabled tools and keeps exclusions independent across operations', () => {
        fs.writeFileSync(
            filePath,
            stringify({
                tools: {
                    'things-create': { operation: 'things_create', enabled: false },
                    'things-email-create': { operation: 'things_create', enabled: true, exclude_params: ['kind'] },
                    'things-sms-create': { operation: 'things_create', enabled: false, exclude_params: ['name'] },
                    'widgets-create': { operation: 'widgets_create', enabled: true },
                },
            })
        )

        expect(parseToolDefinition(filePath)).toEqual({
            operationIds: new Set(['things_create', 'widgets_create']),
            schemaExclusions: new Map([
                ['things_create', ['kind']],
                ['widgets_create', []],
            ]),
        })
    })
})
