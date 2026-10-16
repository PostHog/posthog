import type { MetricsDashboardVariable } from '~/queries/schema/schema-general'

import {
    ALL_OPTION,
    applyVariableRegex,
    orderVariables,
    reconcileSelection,
    selectionFromValues,
    selectionsForRequest,
    variableLevels,
    variablesToReload,
} from './metricVariables'

const custom = (name: string, values: string[]): MetricsDashboardVariable => ({
    name,
    source: 'custom',
    customValues: ['a', 'b'],
    current: { values },
})
const promql = (name: string, query: string): MetricsDashboardVariable => ({ name, source: 'promql', query })

const cluster = custom('cluster', ['a'])
const job = promql('job', 'label_values(up{cluster="$cluster"}, job)')
const instance = promql('instance', 'label_values(up{job=~"${job:regex}"}, instance)')

describe('metricVariables', () => {
    it('orders variables after the variables their queries refer to, and finds loops', () => {
        expect(orderVariables([instance, job, cluster])).toEqual({ order: ['cluster', 'job', 'instance'], cycle: [] })
        expect(orderVariables([promql('x', 'label_values(up{a="$y"}, a)'), promql('y', 'metrics($x)')]).cycle).toEqual([
            'x',
            'y',
        ])
        expect(orderVariables([promql('job', 'label_values(up{job="$job"}, job)')]).cycle).toEqual(['job'])
    })

    it('groups variables that can load at once', () => {
        const zone = custom('zone', ['a'])
        expect(variableLevels([instance, job, cluster, zone])).toEqual([['cluster', 'zone'], ['job'], ['instance']])
    })

    it('sends the loaded options of a variable set to All', () => {
        const all = { ...custom('zone', []), includeAll: true, current: { values: [], all: true } }
        expect(selectionsForRequest([all, cluster], { zone: ['a', 'b'] })).toEqual([
            { name: 'zone', values: ['a', 'b'], all: true, allValue: null },
            { name: 'cluster', values: ['a'], all: false, allValue: null },
        ])
    })

    it.each([
        [
            'a selection reloads the variables that depend on it',
            { ...cluster, current: { values: ['b'] } },
            ['job', 'instance'],
        ],
        [
            'a new definition reloads the variable and its dependents',
            { ...cluster, customValues: ['c'] },
            ['cluster', 'job', 'instance'],
        ],
    ])('%s', (_name, changed, expected) => {
        expect(variablesToReload([cluster, job, instance], [changed, job, instance])).toEqual(expected)
    })

    it.each([
        ['keeps a value that is still an option', { values: ['b'] }, ['a', 'b'], { values: ['b'] }],
        ['replaces a value that is gone with the first option', { values: ['x'] }, ['a', 'b'], { values: ['a'] }],
        ['keeps All without values', { values: ['x'], all: true }, ['a', 'b'], { values: [], all: true }],
    ])('%s', (_name, current, options, expected) => {
        expect(reconcileSelection({ ...custom('v', []), includeAll: true, current }, options)).toEqual(expected)
    })

    it.each([
        ['picking every option means All', true, ['a', 'b'], { values: [], all: true }],
        ['picking the All option means All', false, [ALL_OPTION], { values: [], all: true }],
        ['picking some options keeps them', true, ['b'], { values: ['b'] }],
        ['picking nothing clears the selection', true, [], null],
    ])('%s', (_name, multi, values, expected) => {
        expect(selectionFromValues({ ...custom('v', []), includeAll: true, multi }, values, ['a', 'b'])).toEqual(
            expected
        )
    })

    it.each([
        ['^api', ['api-1', 'web-1'], ['api-1']],
        ['/api-(.*)/', ['api-1', 'api-2', 'web-1'], ['1', '2']],
        ['(', ['a'], ['a']],
        ['/API-(.*)/i', ['api-1', 'web-1'], ['1']],
        ['^(a+)+$', ['a'.repeat(40) + 'b', 'aa'], ['aa']],
    ])('applies the regex %s', (regex, options, expected) => {
        expect(applyVariableRegex(options, regex)).toEqual(expected)
    })
})
