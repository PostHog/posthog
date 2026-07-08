import { describe, expect, it } from 'vitest'

import { takeOption } from '@/cli/args'

describe('CLI argument helpers', () => {
    it('removes and returns an option value', () => {
        const args = ['install', '--path', 'docs/AGENTS.md', '--force']

        expect(takeOption(args, '--path')).toBe('docs/AGENTS.md')
        expect(args).toEqual(['install', '--force'])
    })

    it('returns undefined when the option is absent', () => {
        const args = ['install']

        expect(takeOption(args, '--path')).toBeUndefined()
        expect(args).toEqual(['install'])
    })

    it('rejects an option with no value', () => {
        const args = ['install', '--path']

        expect(() => takeOption(args, '--path')).toThrow('Missing value for --path')
    })

    it('rejects another flag where the option value should be', () => {
        const args = ['install', '--path', '--force']

        expect(() => takeOption(args, '--path')).toThrow('Missing value for --path')
    })
})
