import type { MetricsDashboardVariable } from '~/queries/schema/schema-general'

import { variableErrors } from './metricVariableEditorLogic'
import {
    ALL_OPTION,
    dependentsOf,
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
        const sqlWithComments: MetricsDashboardVariable = {
            name: 'env',
            source: 'sql',
            query: "SELECT 'prod' -- $env\n/* $env */ // $env\n# $env",
        }
        expect(orderVariables([sqlWithComments]).cycle).toEqual([])
        const escaped = [promql('env', 'label_values(up{a=~`\\$env`, b=~"\\\\$env"}, env) # $env')]
        expect(orderVariables(escaped).cycle).toEqual([])
        expect(orderVariables([promql('env', 'label_values(up{c="C:\\\\$env"}, env)')]).cycle).toEqual(['env'])
        const namedGroup = 'query_result(label_replace(up, "dst", "$env", "src", "(?P<env>.*)"))'
        expect(orderVariables([promql('env', namedGroup)]).cycle).toEqual([])
        const longQuery = `query_result(up{a="${'x'.repeat(8000)}"}${' + sum(up)'.repeat(20)})`
        const started = performance.now()
        orderVariables([promql('env', longQuery)])
        expect(performance.now() - started).toBeLessThan(200)
        expect(dependentsOf([cluster, promql('job', namedGroup.replace('$env', '$cluster'))], ['cluster'])).toEqual([
            'job',
        ])
        const sqlWithCarriageReturn: MetricsDashboardVariable = {
            name: 'env',
            source: 'sql',
            query: 'SELECT 1 -- note\rWHERE env = $env',
        }
        expect(orderVariables([sqlWithCarriageReturn]).cycle).toEqual(['env'])
    })

    it.each([
        ['a SQL query gets the loaded options of All', 'sql', 'SELECT a WHERE zone IN $zone', ['a', 'b']],
        ['a PromQL query matches everything without them', 'promql', 'label_values(up{zone=~"$zone"}, a)', []],
    ])('%s, and only of the variables it refers to', (_name, source, text, values) => {
        const zone = { ...custom('zone', []), includeAll: true, current: { values: [], all: true } }
        const query = { name: 'q', source, query: text } as MetricsDashboardVariable
        expect(selectionsForRequest(query, [zone, cluster, query], { zone: ['a', 'b'] })).toEqual([
            { name: 'zone', values, all: true, allValue: null },
        ])
    })

    it.each([
        ['loaded options, which can be none', { zone: [] }, [{ name: 'zone', values: [], all: true, allValue: null }]],
        ['options that have not loaded', {}, []],
    ])('a SQL query sends All with %s', (_name, options, expected) => {
        const zone = { ...custom('zone', []), includeAll: true, current: { values: [], all: true } }
        const query: MetricsDashboardVariable = { name: 'q', source: 'sql', query: 'SELECT a WHERE zone IN $zone' }
        expect(selectionsForRequest(query, [zone, query], options)).toEqual(expected)
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
        ['a regex over the API limit', 'promql', 'a'.repeat(1025), 'regex'],
        ['a list, which does not use the regex', 'custom', 'a'.repeat(1025), undefined],
        ['a PromQL query that is not an options function', 'promql', undefined, 'query', 'up'],
        ['an options function in capitals', 'promql', undefined, 'query', 'LABEL_VALUES(job)'],
        ['a query that refers to a missing variable', 'promql', undefined, 'query', 'label_values(up{a="$gone"}, b)'],
        [
            'a query with built-in and group references',
            'promql',
            undefined,
            undefined,
            'query_result(rate(up[$__range]))',
        ],
    ])('checks %s', (_name, source, regex, field, query = 'label_values(job)') => {
        const variable = { name: 'v', source, query, customValues: ['a'], regex }
        expect(ownValue(variableErrors([variable as MetricsDashboardVariable]), 'v')?.field).toEqual(field)
    })

    it.each(['__proto__', '__interval'])('rejects the reserved name %s', (name) => {
        const errors = variableErrors([{ name, source: 'promql', query: 'label_values(job)' }])
        expect(ownValue(errors, name)?.field).toEqual('name')
    })

    it('keeps an option that looks like the All value when the variable has no All', () => {
        const variable: MetricsDashboardVariable = { name: 'v', source: 'custom', customValues: ['$__all'] }
        expect(selectionFromValues(variable, ['$__all'], ['$__all'])).toEqual({ values: ['$__all'] })
    })
})
