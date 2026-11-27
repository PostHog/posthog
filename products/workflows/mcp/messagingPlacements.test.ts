import { type FlagReader, placementState } from './messagingPlacements'

const DEFAULT_COPY = {
    label: 'Email the people in this cohort',
    description: 'The user can send this cohort an email. They review and launch it in the broadcast editor.',
}

const COHORT_PLACEMENT = {
    key: 'mcp.after_cohorts_create',
    area: 'mcp',
    variant: 'after_cohorts_create',
    defaultCopy: DEFAULT_COPY,
}

function flagReader(values: Record<string, boolean | string>, payloads: Record<string, unknown> = {}): FlagReader {
    return {
        value: (flag) => values[flag],
        payload: (flag) => payloads[flag],
    }
}

describe('placementState', () => {
    test.each([
        {
            name: 'the holdout variant holds the spot out',
            flags: flagReader({ 'xpm-mcp-placement': 'holdout-7' }),
            expected: { active: false, reason: 'holdout' },
        },
        {
            name: 'the control variant leaves the spot inactive',
            flags: flagReader({ 'xpm-mcp-placement': 'control' }),
            expected: { active: false, reason: 'not_this_variant' },
        },
        {
            name: 'an unevaluated flag leaves the spot inactive',
            flags: flagReader({}),
            expected: { active: false, reason: 'not_this_variant' },
        },
        {
            name: 'a boolean flag leaves the spot inactive',
            flags: flagReader({ 'xpm-mcp-placement': true }),
            expected: { active: false, reason: 'not_this_variant' },
        },
        {
            name: "another area's flag on this variant leaves the spot inactive",
            flags: flagReader({ 'xpm-cohorts-placement': 'after_cohorts_create' }),
            expected: { active: false, reason: 'not_this_variant' },
        },
        {
            name: 'this variant without a payload shows the default copy',
            flags: flagReader({ 'xpm-mcp-placement': 'after_cohorts_create' }),
            expected: { active: true, placement: COHORT_PLACEMENT, copy: DEFAULT_COPY },
        },
        {
            name: 'this variant with a valid payload shows its copy',
            flags: flagReader(
                { 'xpm-mcp-placement': 'after_cohorts_create' },
                { 'xpm-mcp-placement': { label: 'Send this cohort an email' } }
            ),
            expected: { active: true, placement: COHORT_PLACEMENT, copy: { label: 'Send this cohort an email' } },
        },
        {
            name: 'this variant with an invalid payload falls back to the default copy',
            flags: flagReader(
                { 'xpm-mcp-placement': 'after_cohorts_create' },
                { 'xpm-mcp-placement': { label: '', description: 'An empty label' } }
            ),
            expected: { active: true, placement: COHORT_PLACEMENT, copy: DEFAULT_COPY },
        },
        {
            name: 'this variant with a blank label falls back to the default copy',
            flags: flagReader(
                { 'xpm-mcp-placement': 'after_cohorts_create' },
                { 'xpm-mcp-placement': { label: '  ' } }
            ),
            expected: { active: true, placement: COHORT_PLACEMENT, copy: DEFAULT_COPY },
        },
        {
            name: 'this variant with a payload that is not an object falls back to the default copy',
            flags: flagReader(
                { 'xpm-mcp-placement': 'after_cohorts_create' },
                { 'xpm-mcp-placement': 'Email this cohort' }
            ),
            expected: { active: true, placement: COHORT_PLACEMENT, copy: DEFAULT_COPY },
        },
    ])('$name', ({ flags, expected }) => {
        expect(placementState('mcp.after_cohorts_create', flags)).toEqual(expected)
    })
})
