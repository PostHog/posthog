import { describe, expect, it } from 'vitest'

import type { Context } from '../src/expressions.ts'
import { type Outcome, type Scenario, parseWorkflow, planWorkflow } from '../src/plan.ts'
import { allFiltersChanged, pullRequest, push } from '../src/scenarios.ts'

const scenario = (overrides: Partial<Scenario> = {}, github: Context = pullRequest()): Scenario => ({
    name: 'test',
    github,
    ...overrides,
})

// Workflows write `!cancelled()` in a block scalar because a bare `!` starts a YAML tag.
const block = (condition: string): string => `>-\n      ${condition.split('\n').join('\n      ')}`

const twoJobs = (condition: string | undefined): string => `
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    steps: [{ run: echo }]
  b:
    needs: a
    ${condition === undefined ? '' : `if: ${block(condition)}`}
    runs-on: ubuntu-latest
    steps: [{ run: echo }]
`

describe('planWorkflow', () => {
    it.each<{ condition: string | undefined; upstream: Outcome; expected: Outcome }>([
        { condition: "github.event_name == 'push'", upstream: 'failure', expected: 'skipped' },
        { condition: "!cancelled() && github.event_name == 'push'", upstream: 'failure', expected: 'success' },
        { condition: 'always()', upstream: 'failure', expected: 'success' },
        { condition: 'failure()', upstream: 'failure', expected: 'success' },
        { condition: 'failure()', upstream: 'success', expected: 'skipped' },
        { condition: undefined, upstream: 'skipped', expected: 'skipped' },
        { condition: '!cancelled()', upstream: 'skipped', expected: 'success' },
    ])(
        'applies success() implicitly: if=$condition after upstream=$upstream gives $expected',
        ({ condition, upstream, expected }) => {
            const source = twoJobs(condition).replace(
                'runs-on: ubuntu-latest\n    steps: [{ run: echo }]\n  b:',
                `if: ${upstream === 'skipped' ? 'false' : 'true'}\n    runs-on: ubuntu-latest\n    steps: [{ run: echo }]\n  b:`
            )
            const plan = planWorkflow(
                parseWorkflow(source),
                scenario({ failJobs: upstream === 'failure' ? ['a'] : [] }, push())
            )
            expect(plan.jobs['b']?.result).toBe(expected)
        }
    )

    it.each<{ condition: string; flag: string; expected: Outcome }>([
        { condition: '${{ !cancelled() }}', flag: 'false', expected: 'cancelled' },
        { condition: 'always()', flag: 'false', expected: 'success' },
        { condition: "!cancelled() || needs.a.outputs.flag == 'true'", flag: 'true', expected: 'success' },
        { condition: "!cancelled() || needs.a.outputs.flag == 'true'", flag: 'false', expected: 'cancelled' },
    ])(
        'records a gate on a cancelled run: if=$condition with flag=$flag gives $expected',
        ({ condition, flag, expected }) => {
            const source = `
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    outputs:
      flag: \${{ steps.verdict.outputs.flag }}
    steps: [{ id: verdict, run: echo }]
  b:
    needs: a
    if: ${block(condition)}
    runs-on: ubuntu-latest
    steps: [{ run: echo }]
`
            const plan = planWorkflow(
                parseWorkflow(source),
                scenario({
                    cancelled: true,
                    completedBeforeCancel: ['a'],
                    steps: { a: { verdict: { outputs: { flag } } } },
                })
            )
            expect(plan.jobs['b']?.result).toBe(expected)
        }
    )

    it('reads empty outputs from a skipped job and drops outputs of a skipped step', () => {
        const source = `
on: push
jobs:
  changes:
    if: github.event_name != 'push'
    runs-on: ubuntu-latest
    outputs:
      backend: \${{ steps.filter.outputs.backend || 'true' }}
    steps:
      - id: filter
        if: github.event_name != 'schedule'
        run: echo
  consumer:
    needs: changes
    if: '!cancelled()'
    runs-on: ubuntu-latest
    outputs:
      backend: \${{ needs.changes.outputs.backend || 'default' }}
    steps: [{ run: echo }]
`
        const workflow = parseWorkflow(source)
        const stubs = { changes: { filter: { outputs: { backend: 'false' } } } }

        const onPr = planWorkflow(workflow, scenario({ steps: stubs }))
        expect(onPr.jobs['changes']?.outputs).toEqual({ backend: 'false' })

        const onPush = planWorkflow(workflow, scenario({ steps: stubs }, push()))
        expect(onPush.jobs['changes']?.outputs).toEqual({})
        expect(onPush.jobs['consumer']?.outputs).toEqual({ backend: 'default' })

        const filterSkipped = planWorkflow(
            workflow,
            scenario({ steps: stubs }, { ...pullRequest(), event_name: 'schedule' })
        )
        expect(filterSkipped.jobs['changes']?.outputs).toEqual({ backend: 'true' })
    })

    it('skips steps after a failure unless a status function or continue-on-error says otherwise', () => {
        const source = `
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - id: flaky
        continue-on-error: true
        run: echo
      - id: after-tolerated
        if: steps.flaky.outcome == 'failure' && steps.flaky.conclusion == 'success'
        run: echo
      - id: broken
        run: echo
      - id: plain
        run: echo
      - id: on-failure
        if: failure()
        run: echo
      - id: cleanup
        if: always()
        run: echo
`
        const plan = planWorkflow(
            parseWorkflow(source),
            scenario({ steps: { a: { flaky: { outcome: 'failure' }, broken: { outcome: 'failure' } } } })
        )
        const runs = Object.fromEntries(plan.jobs['a']!.steps.map((step) => [step.id, step.runs]))
        expect(runs).toEqual({
            flaky: true,
            'after-tolerated': true,
            broken: true,
            plain: false,
            'on-failure': true,
            cleanup: true,
        })
        expect(plan.jobs['a']?.result).toBe('failure')
    })

    it.each<{ condition: string; expected: Outcome }>([
        { condition: '${{ github.event.pull_request.draft != true }}', expected: 'success' },
        { condition: "contains(github.event.pull_request.labels.*.name, 'no-ci')", expected: 'success' },
        { condition: "contains(github.event.pull_request.labels.*.name, 'run-ci-backend')", expected: 'skipped' },
        {
            condition: "github.event_name != 'pull_request'\n|| startsWith(github.head_ref, 'feat/')",
            expected: 'success',
        },
        { condition: 'false', expected: 'skipped' },
        { condition: "env.INTERNAL == 'true'", expected: 'success' },
    ])('evaluates the condition forms workflows use: $condition', ({ condition, expected }) => {
        const source = `
on: pull_request
jobs:
  a:
    if: ${block(condition)}
    runs-on: ubuntu-latest
    env:
      INTERNAL: \${{ github.event.pull_request.head.repo.full_name == github.repository }}
    steps: [{ run: echo }]
`
        const plan = planWorkflow(parseWorkflow(source), scenario({}, pullRequest({ labels: ['no-ci'] })))
        expect(plan.errors).toEqual([])
        expect(plan.jobs['a']?.result).toBe(expected)
    })

    it.each<{ matrix: string; output: string; expected: number }>([
        { matrix: '${{ fromJSON(needs.a.outputs.m) }}', output: '{"include":[]}', expected: 0 },
        { matrix: '${{ fromJSON(needs.a.outputs.m) }}', output: '{"include":[{"g":1},{"g":2}]}', expected: 2 },
        { matrix: '\n        include: ${{ fromJSON(needs.a.outputs.m) }}', output: '[{"g":1}]', expected: 1 },
        { matrix: '\n        os: [a, b]\n        node: [1, 2]', output: '', expected: 4 },
        {
            matrix: "${{ needs.a.outputs.m != '' && fromJSON(needs.a.outputs.m) || fromJSON('{\"shard\":[1]}') }}",
            output: '',
            expected: 1,
        },
    ])('counts matrix cells for $matrix with output $output', ({ matrix, output, expected }) => {
        const source = `
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    outputs:
      m: \${{ steps.s.outputs.m }}
    steps: [{ id: s, run: echo }]
  b:
    needs: a
    runs-on: ubuntu-latest
    strategy:
      matrix: ${matrix}
    steps: [{ run: echo }]
`
        const plan = planWorkflow(parseWorkflow(source), scenario({ steps: { a: { s: { outputs: { m: output } } } } }))
        expect(plan.errors).toEqual([])
        expect(plan.jobs['b']?.matrixCells).toBe(expected)
    })

    it('records an evaluation error without abandoning the rest of the plan', () => {
        const source = `
on: push
jobs:
  a:
    if: unknownFunction()
    runs-on: ubuntu-latest
    steps: [{ run: echo }]
  b:
    runs-on: ubuntu-latest
    steps: [{ run: echo }]
`
        const plan = planWorkflow(parseWorkflow(source), scenario())
        expect(plan.errors.map((error) => [error.job, error.where])).toEqual([['a', 'if']])
        expect(plan.jobs['b']?.result).toBe('success')
    })

    it('stubs every filter of a paths-filter step as changed, from block-string or mapping filters', () => {
        const source = `
on: push
jobs:
  changes:
    runs-on: ubuntu-latest
    steps:
      - uses: ./.github/actions/paths-filter
        id: filter
        with:
          filters: |
            backend:
              - 'posthog/**'
            docs:
              - 'docs/**'
  other:
    runs-on: ubuntu-latest
    steps:
      - uses: dorny/paths-filter@abc
        id: changed
        with:
          filters:
            rust: ['rust/**']
`
        const stubs = allFiltersChanged(parseWorkflow(source))
        expect(stubs['changes']?.['filter']?.outputs).toMatchObject({
            backend: 'true',
            docs: 'true',
            backend_files: expect.any(String),
        })
        expect(stubs['other']?.['changed']?.outputs).toMatchObject({ rust: 'true', changes: '["rust"]' })
    })
})
