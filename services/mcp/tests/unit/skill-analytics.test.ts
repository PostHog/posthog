import { describe, expect, it } from 'vitest'

import { parseExecCallInnerArgs } from '@/tools/exec'
import { skillAnalyticsProperties } from '@/tools/skills/analytics'

/**
 * These lock in three regressions: a skill read that records no skill (the whole
 * point), an agent-supplied string reaching analytics unvalidated, and a paged
 * continuation counted as a fresh load.
 */
describe('skillAnalyticsProperties', () => {
    it.each([
        ['skill-get', { skill_name: 'conductor' }, 'conductor'],
        ['skill-file-get', { skill_name: 'conductor', file_path: 'references/x.md' }, 'conductor'],
        // The deprecated aliases reach analytics under their own name, so a set that
        // lists only the canonical names is a silent hole.
        ['llma-skill-get', { skill_name: 'conductor' }, 'conductor'],
        ['llma-skill-file-get', { skill_name: 'conductor' }, 'conductor'],
        // Digits and internal hyphens are legal in a stored name.
        ['skill-get', { skill_name: 'signals-scout-v2' }, 'signals-scout-v2'],
        ['skill-get', { skill_name: 'a'.repeat(64) }, 'a'.repeat(64)],
    ])('identifies the skill %s read', (tool, args, expected) => {
        expect(skillAnalyticsProperties(tool, args)).toMatchObject({ $mcp_skill_name: expected })
    })

    it.each([
        // Stamping a non-skill tool would put caller text on unrelated events.
        ['a non-skill tool', 'execute-sql', { skill_name: 'conductor' }],
        ['skill-list, which reads no single skill', 'skill-list', { search: 'conductor' }],
        // Writes already emit `llma skill *` server-side; stamping here too would
        // give two sources that disagree.
        ['a write tool', 'skill-update', { skill_name: 'conductor' }],
        ['an unresolved tool name', undefined, { skill_name: 'conductor' }],
    ])('records nothing for %s', (_label, tool, args) => {
        expect(skillAnalyticsProperties(tool, args)).toEqual({})
    })

    // The rule `execCommandAnalyticsProperties` states: recorded values are value-free
    // by construction. A name is recordable only if it matches the shape the store
    // enforces at creation — anything else is the agent's own text.
    it.each([
        ['spaces', 'my skill'],
        ['uppercase', 'Conductor'],
        ['path traversal', '../../etc/passwd'],
        ['a url', 'https://example.com/x'],
        ['empty', ''],
        ['a leading hyphen', '-conductor'],
        ['over 64 characters', 'a'.repeat(65)],
        ['sql-ish text', "conductor'; DROP TABLE--"],
        ['newlines', 'conductor\nsecond'],
        ['a non-string', 42],
        ['null', null],
        ['an object', { nested: true }],
    ])('drops a skill name that is %s', (_label, value) => {
        expect(skillAnalyticsProperties('skill-get', { skill_name: value })).toEqual({})
    })

    // Analytics must never break a tool call, so malformed input yields no properties
    // rather than throwing.
    it.each([
        ['undefined', undefined],
        ['null', null],
        ['a string', 'skill_name=conductor'],
        ['an empty object', {}],
    ])('returns empty for %s args', (_label, args) => {
        expect(skillAnalyticsProperties('skill-get', args)).toEqual({})
    })

    describe('body offset', () => {
        // skill-get returns a body in slices, so one skill load is several calls that
        // differ only by offset. Without this, count() overstates loads several-fold.
        it.each([
            ['the first page', 0, 0],
            ['a continuation', 5000, 5000],
            ['a numeric string', '5000', 5000],
        ])('records %s', (_label, input, expected) => {
            expect(skillAnalyticsProperties('skill-get', { skill_name: 'conductor', body_offset: input })).toEqual({
                $mcp_skill_name: 'conductor',
                $mcp_skill_body_offset: expected,
            })
        })

        it.each([
            ['absent', undefined],
            ['negative', -1],
            ['not a number', 'later'],
            ['NaN', Number.NaN],
            ['infinite', Number.POSITIVE_INFINITY],
            ['fractional', 1.5],
        ])('omits an offset that is %s, so its absence means "whole body"', (_label, value) => {
            expect(skillAnalyticsProperties('skill-get', { skill_name: 'conductor', body_offset: value })).toEqual({
                $mcp_skill_name: 'conductor',
            })
        })

        it('omits the offset for skill-file-get, which does not paginate a body', () => {
            expect(skillAnalyticsProperties('skill-file-get', { skill_name: 'conductor', body_offset: 10 })).toEqual({
                $mcp_skill_name: 'conductor',
            })
        })
    })
})

/**
 * Nearly all skill reads arrive through the single `exec` dispatcher, where arguments
 * live inside a command string. A property derived only from tool arguments would
 * miss all of them.
 */
describe('parseExecCallInnerArgs', () => {
    it.each([
        ['a call command', 'call skill-get {"skill_name":"conductor"}', { skill_name: 'conductor' }],
        ['a --json flag', 'call --json skill-get {"skill_name":"conductor"}', { skill_name: 'conductor' }],
        ['a --confirm flag', 'call --confirm skill-get {"skill_name":"conductor"}', { skill_name: 'conductor' }],
        [
            'extra whitespace and more keys',
            'call   skill-get   {"skill_name":"conductor","version":4}',
            { skill_name: 'conductor', version: 4 },
        ],
        // The dispatcher treats a body-less call as `{}`; this must match it.
        ['no JSON body', 'call skill-list', {}],
    ])('extracts inner arguments from %s', (_label, command, expected) => {
        expect(parseExecCallInnerArgs(command)).toEqual(expected)
    })

    it.each([
        ['a non-call verb', 'info skill-get'],
        ['an empty command', ''],
        ['invalid JSON', 'call skill-get {not json}'],
        ['a JSON scalar', 'call skill-get 5'],
        ['a JSON array', 'call skill-get ["conductor"]'],
        ['JSON null', 'call skill-get null'],
    ])('returns undefined for %s', (_label, command) => {
        expect(parseExecCallInnerArgs(command)).toBeUndefined()
    })
})
