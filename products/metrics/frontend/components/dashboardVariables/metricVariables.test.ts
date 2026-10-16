import type { MetricsDashboardVariable } from '~/queries/schema/schema-general'

import { applyVariableRegex, orderVariables, reconcileSelection, variablesToReload } from './metricVariables'

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
        ['makes All follow the options', { values: ['x'], all: true }, ['a', 'b'], { values: ['a', 'b'], all: true }],
    ])('%s', (_name, current, options, expected) => {
        expect(reconcileSelection({ ...custom('v', []), includeAll: true, current }, options)).toEqual(expected)
    })

    it.each([
        ['^api', ['api-1', 'web-1'], ['api-1']],
        ['/api-(.*)/', ['api-1', 'api-2', 'web-1'], ['1', '2']],
        ['(', ['a'], ['a']],
    ])('applies the regex %s', (regex, options, expected) => {
        expect(applyVariableRegex(options, regex)).toEqual(expected)
    })
})
