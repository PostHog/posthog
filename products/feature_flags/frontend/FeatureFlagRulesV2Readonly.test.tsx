import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, waitFor, within } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, FeatureFlagRulesV2Config, PropertyFilterType, PropertyOperator } from '~/types'

import { FeatureFlagRulesV2Readonly } from './FeatureFlagRulesV2Readonly'

const CONFIG: FeatureFlagRulesV2Config = {
    version: 2,
    return_type: 'boolean',
    default_value: false,
    rules: [
        {
            id: 'rule-1',
            rule_type: 'percentage_rollout',
            description: 'Half of everyone',
            targeting: { properties: [] },
            value: true,
            rollout_percentage: 50,
            on_rollout_miss: 'return_default',
            assignment_algorithm: 'sha1_v1',
            seed: 'seed-must-not-render',
        },
    ],
}

/** The base config with one rule targeting `property`. */
const withTargeting = (property: AnyPropertyFilter): FeatureFlagRulesV2Config => ({
    ...CONFIG,
    rules: [{ ...CONFIG.rules[0], targeting: { properties: [property] } }],
})

describe('FeatureFlagRulesV2Readonly', () => {
    beforeEach(() => {
        useMocks({
            post: {
                '/api/projects/:team/feature_flags/user_blast_radius': () => [200, { affected: 200, total: 2000 }],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('shows a holdout by its exclusion percentage but never its seed', () => {
        const config: FeatureFlagRulesV2Config = {
            ...CONFIG,
            rules: [
                {
                    id: 'rule-3',
                    rule_type: 'experiment',
                    targeting: { properties: [] },
                    rollout_percentage: 100,
                    on_rollout_miss: 'continue',
                    assignment_algorithm: 'sha1_60_v1',
                    seed: 'seed-must-not-render',
                    paused: false,
                    variants: [
                        { key: 'control', weight: 50, value: false },
                        { key: 'test', weight: 50, value: true },
                    ],
                    holdout: { seed: 'holdout-seed-must-not-render', exclusion_percentage: 10 },
                },
            ],
        }
        const { container } = render(
            <Provider>
                <FeatureFlagRulesV2Readonly config={config} />
            </Provider>
        )

        expect(container).toHaveTextContent('Holdout excludes 10%')
        expect(container).not.toHaveTextContent('seed-must-not-render')
    })

    it('shows the rule but never its seed', () => {
        const { container } = render(
            <Provider>
                <FeatureFlagRulesV2Readonly config={CONFIG} />
            </Provider>
        )

        expect(container).toHaveTextContent('Half of everyone')
        expect(container).toHaveTextContent('50%')
        expect(container).not.toHaveTextContent('seed-must-not-render')
    })

    it('labels every experiment rule "Experiment" and shows its variants, pause and holdout', () => {
        const experimentRule = {
            rule_type: 'experiment' as const,
            targeting: { properties: [] },
            paused: true,
            rollout_percentage: 50,
            on_rollout_miss: 'continue' as const,
            assignment_algorithm: 'sha1_60_v1',
            seed: 'rule-seed-must-not-render',
            variants: [
                { key: 'control', weight: 33.34, value: 'standard' },
                { key: 'compact', weight: 66.66, value: 'compact-layout' },
            ],
        }
        const { container } = render(
            <Provider>
                <FeatureFlagRulesV2Readonly
                    config={{
                        version: 2,
                        return_type: 'string',
                        default_value: null,
                        rules: [
                            {
                                ...experimentRule,
                                id: 'rule-paused',
                                holdout: { seed: 'holdout-seed-must-not-render', exclusion_percentage: 5 },
                            },
                            { ...experimentRule, id: 'rule-running', paused: false },
                        ],
                    }}
                />
            </Provider>
        )

        const [pausedRule, runningRule] = Array.from(container.querySelectorAll('[data-attr="rules-v2-rule-readonly"]'))
        expect(pausedRule).toHaveTextContent('Experiment')
        expect(pausedRule).toHaveTextContent('Paused')
        expect(pausedRule).toHaveTextContent('Matching users get the default value')
        const variants = Array.from(pausedRule.querySelectorAll('[data-attr="rules-v2-variant-readonly"]'))
        expect(variants.map((variant) => variant.textContent)).toEqual([
            'control33.34%standard',
            'compact66.66%compact-layout',
        ])
        expect(pausedRule).toHaveTextContent('50% of the rest are enrolled. The others continue to the next rule.')
        expect(pausedRule).toHaveTextContent('Holdout excludes 5%')
        expect(runningRule).toHaveTextContent('Experiment')
        expect(runningRule).not.toHaveTextContent('Paused')
        expect(runningRule).not.toHaveTextContent('Holdout')
        expect(container).not.toHaveTextContent('must-not-render')
    })

    it('ends the rules with the default value, and estimates who each rule matches and reaches', async () => {
        const { container } = render(
            <Provider>
                <FeatureFlagRulesV2Readonly config={CONFIG} />
            </Provider>
        )

        const rule = container.querySelector('[data-attr="rules-v2-rule-readonly"]')
        await waitFor(() => expect(rule).toHaveTextContent('≈ 200 users'))
        expect(rule).toHaveTextContent('≈ 100 users')
        expect(container.querySelector('[data-attr="rules-v2-default-step"]')).toHaveTextContent(
            'Rule 1 decides the value for every user'
        )
        expect(container.querySelector('[data-attr="rules-v2-default-step"]')).toHaveTextContent('false')
    })

    it('warns about a rule that an earlier rule hides', () => {
        const { container } = render(
            <Provider>
                <FeatureFlagRulesV2Readonly
                    config={{
                        ...CONFIG,
                        rules: [
                            CONFIG.rules[0],
                            {
                                id: 'rule-2',
                                rule_type: 'targeted_release',
                                targeting: { properties: [] },
                                value: true,
                            },
                        ],
                    }}
                />
            </Provider>
        )

        const [first, second] = Array.from(container.querySelectorAll('[data-attr="rules-v2-rule-readonly"]'))
        expect(first.querySelector('[data-attr="rules-v2-rule-unreachable"]')).toBeNull()
        expect(second.querySelector('[data-attr="rules-v2-rule-unreachable"]')).toHaveTextContent(
            'This rule is never reached: rule 1 already decides the value'
        )
    })

    it('shows a paused experiment without an enrolled estimate, since it enrolls no one', async () => {
        const { container } = render(
            <Provider>
                <FeatureFlagRulesV2Readonly
                    config={{
                        ...CONFIG,
                        rules: [
                            {
                                id: 'rule-paused',
                                rule_type: 'experiment',
                                targeting: { properties: [] },
                                paused: true,
                                rollout_percentage: 50,
                                on_rollout_miss: 'continue',
                                assignment_algorithm: 'sha1_60_v1',
                                seed: 'seed',
                                variants: [
                                    { key: 'control', weight: 50, value: false },
                                    { key: 'test', weight: 50, value: true },
                                ],
                            },
                        ],
                    }}
                />
            </Provider>
        )

        const rule = container.querySelector('[data-attr="rules-v2-rule-readonly"]')
        await waitFor(() => expect(rule).toHaveTextContent('≈ 200 users'))
        expect(rule).not.toHaveTextContent('≈ 100 users')
    })

    it.each([
        { status: 500, retry: true },
        { status: 400, retry: false },
    ])('offers a retry after a failed estimate only when one can help (status $status)', async ({ status, retry }) => {
        useMocks({
            post: { '/api/projects/:team/feature_flags/user_blast_radius': () => [status, { detail: 'Failed.' }] },
        })
        const { container } = render(
            <Provider>
                <FeatureFlagRulesV2Readonly config={CONFIG} />
            </Provider>
        )

        const rule = container.querySelector('[data-attr="rules-v2-rule-readonly"]')
        await waitFor(() => expect(rule).toHaveTextContent("Couldn't estimate"))
        expect(rule?.textContent?.includes('Retry')).toBe(retry)
    })

    it('estimates again on Retry, since a failed estimate is not kept', async () => {
        useMocks({
            post: { '/api/projects/:team/feature_flags/user_blast_radius': () => [500, { detail: 'Failed.' }] },
        })
        const { container } = render(
            <Provider>
                <FeatureFlagRulesV2Readonly config={CONFIG} />
            </Provider>
        )
        const rule = container.querySelector<HTMLElement>('[data-attr="rules-v2-rule-readonly"]')!
        await waitFor(() => expect(rule).toHaveTextContent('Retry'))

        useMocks({
            post: {
                '/api/projects/:team/feature_flags/user_blast_radius': () => [200, { affected: 200, total: 2000 }],
            },
        })
        fireEvent.click(within(rule).getAllByText('Retry')[0])

        await waitFor(() => expect(rule).toHaveTextContent('≈ 200 users'))
    })

    it('does not estimate a rule while one of its conditions has no value', async () => {
        const estimate = jest.fn(() => [200, { affected: 200, total: 2000 }])
        useMocks({ post: { '/api/projects/:team/feature_flags/user_blast_radius': estimate } })
        const { container } = render(
            <Provider>
                <FeatureFlagRulesV2Readonly
                    config={withTargeting({
                        key: 'email',
                        type: PropertyFilterType.Person,
                        operator: PropertyOperator.Exact,
                        value: [],
                    })}
                />
            </Provider>
        )

        await act(async () => {})
        expect(estimate).not.toHaveBeenCalled()
        expect(container.querySelector('[data-attr="rules-v2-rule-readonly"]')).not.toHaveTextContent('≈')
        expect(container.querySelector('[data-attr="rules-v2-rule-readonly"]')).not.toHaveTextContent('Estimating')
    })

    it('estimates a group flag over its group type and links to the matching groups', async () => {
        const groupTypeIndexes: unknown[] = []
        useMocks({
            post: {
                '/api/projects/:team/feature_flags/user_blast_radius': async ({ request }) => {
                    groupTypeIndexes.push(((await request.json()) as Record<string, unknown>).group_type_index)
                    return [200, { affected: 30, total: 90 }]
                },
            },
        })
        const { container } = render(
            <Provider>
                <FeatureFlagRulesV2Readonly config={{ ...CONFIG, aggregation_group_type_index: 0 }} />
            </Provider>
        )

        await waitFor(() => expect(container).toHaveTextContent('≈ 30'))
        expect(groupTypeIndexes).toEqual([0])
        expect(container.querySelector('a[href*="/groups/0"]')).toHaveTextContent('≈ 30')
    })

    it('shows a rule type it does not know instead of failing', () => {
        const { container } = render(
            <Provider>
                <FeatureFlagRulesV2Readonly
                    config={{
                        ...CONFIG,
                        rules: [{ id: 'rule-old', rule_type: 'variant_rollout', targeting: { properties: [] } } as any],
                    }}
                />
            </Provider>
        )

        expect(container.querySelector('[data-attr="rules-v2-rule-readonly"]')).toHaveTextContent('variant_rollout')
    })
})
