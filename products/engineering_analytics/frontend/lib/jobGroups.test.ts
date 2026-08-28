import { failedShardsLabel, groupJobs, jobBaseName, stripShardSuffix } from './jobGroups'

// Names below are taken verbatim from real PostHog/posthog runs (see run 28576193541: a
// master push carries ~80 jobs across a multi-dimension Django matrix, sharded and
// list-valued product-test groups, and unexpanded templates when a matrix was skipped).
const DJANGO_CORE = 'Django tests – Core (persons-on-events off), Py 3.13.13, clickhouse:26.3.10'
const DJANGO_TEMPORAL = 'Django tests – Temporal (persons-on-events off), Py 3.13.13, clickhouse:26.3.10'
const DJANGO_TEMPLATE =
    "Django tests – ${{ matrix.segment }}${{ ((matrix.compat && ' compat') || '') }} (persons-on-events ${{ ((matrix.person-on-events && 'on') || 'off') }}), Py ${{ matrix.python-version }} (${{ matrix.group }}/${{ matrix.concurrency }})"

describe('jobGroups', () => {
    test.each([
        // the nested-paren shard: the closing paren must survive the strip
        ['Product tests (experiments (1/2))', 'Product tests (experiments)'],
        ['Product tests (web-analytics)', 'Product tests (web-analytics)'],
        [`${DJANGO_CORE} (3/23)`, DJANGO_CORE],
        ['Lint & types', 'Lint & types'],
        // a bare "(G/N)" suffix without an outer paren group
        ['e2e (chromium) (5/8)', 'e2e (chromium)'],
    ])('stripShardSuffix(%s)', (name, expected) => {
        expect(stripShardSuffix(name)).toBe(expected)
    })

    test.each([
        [`${DJANGO_CORE} (3/23)`, 'Django tests'],
        ['Product tests (experiments (1/2))', 'Product tests'],
        ['Product tests (logs, ai-observability)', 'Product tests'],
        ['Repo checks (depot-ubuntu-latest)', 'Repo checks'],
        ['Django Tests Pass', 'Django Tests Pass'],
        // unexpanded template from a skipped matrix must not crash or leak "${{"
        [DJANGO_TEMPLATE, 'Django tests'],
    ])('jobBaseName(%s)', (name, expected) => {
        expect(jobBaseName(name)).toBe(expected)
    })

    it('groups multi-variant matrices into one base with variant count and shard attribution', () => {
        const jobs = [
            { name: 'Select tests', conclusion: 'success' },
            ...Array.from({ length: 23 }, (_, i) => ({
                name: `${DJANGO_CORE} (${i + 1}/23)`,
                conclusion: i === 2 || i === 16 ? 'failure' : 'success',
            })),
            ...Array.from({ length: 13 }, (_, i) => ({
                name: `${DJANGO_TEMPORAL} (${i + 1}/13)`,
                conclusion: 'success',
            })),
            { name: 'Product tests (experiments (1/2))', conclusion: 'success' },
            { name: 'Product tests (experiments (2/2))', conclusion: 'success' },
            { name: 'Django Tests Pass', conclusion: 'failure' },
        ]
        const groups = groupJobs(jobs)
        expect(groups.map((g) => [g.base, g.jobs.length, g.variants, g.conclusion])).toEqual([
            ['Select tests', 1, 1, 'success'],
            ['Django tests', 36, 2, 'failure'],
            ['Product tests', 2, 1, 'success'],
            ['Django Tests Pass', 1, 1, 'failure'],
        ])
        expect(failedShardsLabel(groups[1])).toBe('shards 3, 17 of 23')
    })

    test.each([
        // any running job keeps the group open, but a failure wins over running
        [[null, 'success'], 'running'],
        [['failure', null], 'failure'],
        [['timed_out', 'success'], 'failure'],
        [['cancelled', 'success'], 'cancelled'],
        [['skipped', 'skipped'], 'skipped'],
    ] as [Array<string | null>, string][])('group conclusion precedence %s → %s', (conclusions, expected) => {
        const groups = groupJobs(
            conclusions.map((c, i) => ({ name: `job (${i + 1}/${conclusions.length})`, conclusion: c }))
        )
        expect(groups).toHaveLength(1)
        expect(groups[0].conclusion).toBe(expected)
    })

    it('labels non-shard failures by cleaned name', () => {
        const groups = groupJobs([{ name: DJANGO_TEMPLATE, conclusion: 'failure' }])
        expect(failedShardsLabel(groups[0])).toContain('Django tests – …')
        expect(failedShardsLabel(groups[0])).not.toContain('${{')
    })
})
