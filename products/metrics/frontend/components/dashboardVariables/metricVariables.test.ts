import type { MetricsDashboardVariable } from '~/queries/schema/schema-general'

import { variableErrors } from './metricVariableEditorLogic'
import {
    ALL_OPTION,
    applyVariableRegex,
    orderVariables,
    ownValue,
    reconcileSelection,
    selectionFromValues,
    selectionsForRequest,
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

    it.each([
        ['a SQL query gets the loaded options of All', 'sql', ['a', 'b']],
        ['a PromQL query matches everything without them', 'promql', []],
    ])('%s, and only of the variables it refers to', (_name, source, values) => {
        const zone = { ...custom('zone', []), includeAll: true, current: { values: [], all: true } }
        const query = { name: 'q', source, query: 'label_values(up{zone=~"$zone"}, a)' } as MetricsDashboardVariable
        expect(selectionsForRequest(query, [zone, cluster, query], { zone: ['a', 'b'] })).toEqual([
            { name: 'zone', values, all: true, allValue: null },
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
        ['a query variable', 'promql', 'regex'],
        ['a list, which does not use the regex', 'custom', undefined],
    ])('checks an invalid regex on %s', (_name, source, field) => {
        const variable = { name: 'v', source, query: 'label_values(job)', customValues: ['a'], regex: '(' }
        expect(ownValue(variableErrors([variable as MetricsDashboardVariable]), 'v')?.field).toEqual(field)
    })

    it.each(['__proto__', '__interval'])('rejects the reserved name %s', (name) => {
        const errors = variableErrors([{ name, source: 'promql', query: 'label_values(job)' }])
        expect(ownValue(errors, name)?.field).toEqual('name')
    })

    it.each([
        ['^api', ['api-1', 'web-1'], ['api-1']],
        [' api', ['api', ' api'], ['api', ' api']],
        ['/api-(.*)/', ['api-1', 'api-2', 'web-1'], ['1', '2']],
        ['(', ['a'], ['a']],
        ['/API-(.*)/i', ['api-1', 'web-1'], ['1']],
        ['^(a+)+$', ['a'.repeat(40) + 'b', 'aa'], ['aa']],
    ])('applies the regex %s', (regex, options, expected) => {
        expect(applyVariableRegex(options, regex)).toEqual(expected)
    })
})
