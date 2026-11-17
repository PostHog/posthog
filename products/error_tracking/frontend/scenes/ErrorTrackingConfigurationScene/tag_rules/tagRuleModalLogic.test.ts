import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import type { MockResolverInfo } from '~/mocks/utils'
import { initKeaTests } from '~/test/init'
import { EventPropertyFilter, FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { issueTagDefinitionsLogic } from '../../../components/IssueFilters/issueTagDefinitionsLogic'
import { issueQueryOptionsLogic } from '../../../components/IssueQueryOptions/issueQueryOptionsLogic'
import { rulesLogic } from '../rules/rulesLogic'
import { ErrorTrackingRuleType, ErrorTrackingTagRule } from '../rules/types'
import { tagRuleModalLogic } from './tagRuleModalLogic'

const TAG_RULES_PATH = `/api/projects/${MOCK_TEAM_ID}/error_tracking/tag_rules/`

const browserFilter: EventPropertyFilter = {
    key: '$browser',
    value: ['Firefox'],
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Event,
}

const persistedRule: ErrorTrackingTagRule = {
    id: 'rule-id',
    key: 'rule_0123',
    label: 'Firefox',
    description: 'Errors from Firefox.',
    filters: { type: FilterLogicalOperator.And, values: [browserFilter] },
    order_key: 0,
    disabled_data: { message: 'The rule failed.' },
    created_at: '2026-11-16T00:00:00Z',
    updated_at: '2026-11-16T00:00:00Z',
}

describe('tagRuleModalLogic', () => {
    let rules: ErrorTrackingTagRule[]
    let requests: { method: string; path: string; body: unknown }[]

    beforeEach(() => {
        rules = [persistedRule]
        requests = []
        const record = async ({ request }: MockResolverInfo): Promise<void> => {
            requests.push({ method: request.method, path: new URL(request.url).pathname, body: await request.json() })
        }
        useMocks({
            get: {
                '/api/projects/:team_id/error_tracking/tag_rules/': () => ({ results: rules }),
                '/api/projects/:team_id/error_tracking/issues/tag_definitions/': () => ({
                    results: rules
                        .filter((rule) => !rule.disabled_data)
                        .map(({ key, label, description }) => ({ key, label, description })),
                }),
            },
            post: {
                '/api/projects/:team_id/error_tracking/tag_rules/': async (info) => {
                    await record(info)
                    return [201, persistedRule]
                },
            },
            put: {
                '/api/projects/:team_id/error_tracking/tag_rules/:id/': async (info) => {
                    await record(info)
                    return [204]
                },
            },
            delete: {
                '/api/projects/:team_id/error_tracking/tag_rules/:id/': ({ params }) => {
                    rules = rules.filter((rule) => rule.id !== params.id)
                    return [204]
                },
            },
        })
        initKeaTests()
    })

    // An edit sends the filters even when only the label changed, because saving the filters re-enables a disabled
    // rule, as the modal's disabled banner says.
    it.each([
        [
            'creates a new rule after the existing ones',
            null,
            'POST',
            TAG_RULES_PATH,
            {
                label: 'Firefox users',
                description: '',
                filters: { type: FilterLogicalOperator.And, values: [browserFilter] },
                order_key: persistedRule.order_key + 1,
            },
        ],
        [
            'saves an edit with its filters',
            persistedRule,
            'PUT',
            `${TAG_RULES_PATH}${persistedRule.id}/`,
            { label: 'Firefox users', description: persistedRule.description, filters: persistedRule.filters },
        ],
    ])('%s and reloads the list', async (_, rule, method, path, body) => {
        const logic = tagRuleModalLogic()
        logic.mount()
        const list = rulesLogic({ ruleType: ErrorTrackingRuleType.Tag })
        await expectLogic(list, () => list.actions.loadRules()).toFinishAllListeners()

        if (rule) {
            logic.actions.openModal(rule)
        } else {
            logic.actions.openModal()
            logic.actions.updateRule({
                ...logic.values.rule,
                filters: { type: FilterLogicalOperator.And, values: [browserFilter] },
            })
        }
        logic.actions.updateLabel('Firefox users')
        await expectLogic(logic, () => logic.actions.saveRule()).toFinishAllListeners()

        expect(requests).toEqual([{ method, path, body }])
        expect(logic.values.isOpen).toBe(false)
        expect(list.values.rules).toEqual([persistedRule])
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    // A rule reads only the first exception of a new issue. A preview that counts every matching exception counts
    // issues that the rule never labels.
    it('previews the first exception of each issue first seen in the selected window', async () => {
        const query = jest.spyOn(api, 'query').mockResolvedValue({ results: [[2, 2]] } as any)
        const logic = tagRuleModalLogic()
        logic.mount()

        logic.actions.openModal(persistedRule)
        await expectLogic(logic, () => logic.actions.increaseDateRange()).toFinishAllListeners()

        expect(query).toHaveBeenCalledWith(
            expect.objectContaining({
                after: '-30d',
                where: [
                    expect.stringMatching(/argMin\(uuid, timestamp\).*issue_first_seen >= now\(\) - INTERVAL 30 DAY/),
                ],
            })
        )
        expect(logic.values.matchResult).toEqual({ exceptionCount: 2, issueCount: 2 })
    })

    // The issue list loads its label definitions once, and the query ignores a label that no longer exists. A filter on
    // a deleted rule's label would then claim to narrow a list it does not narrow.
    it.each(['the rule modal', 'the list'])(
        'clears an open issue list filter on a rule deleted from %s',
        async (deletedFrom) => {
            const enabledRule = { ...persistedRule, disabled_data: null }
            rules = [enabledRule]
            const options = issueQueryOptionsLogic({ logicKey: 'test' })
            options.mount()
            await expectLogic(issueTagDefinitionsLogic, () => {
                issueTagDefinitionsLogic.mount()
            }).toFinishAllListeners()
            options.actions.setIssueTag({ key: enabledRule.key, applied: true })

            const logic = tagRuleModalLogic()
            logic.mount()
            const list = rulesLogic({ ruleType: ErrorTrackingRuleType.Tag })
            await expectLogic(list, () => list.actions.loadRules()).toFinishAllListeners()
            expect(options.values.issueTag).toEqual({ key: enabledRule.key, applied: true })

            if (deletedFrom === 'the rule modal') {
                logic.actions.openModal(enabledRule)
                await expectLogic(logic, () => logic.actions.deleteRule()).toFinishAllListeners()
            } else {
                list.actions.startSelectingRules()
                list.actions.toggleSelectedRule(enabledRule.id)
                await expectLogic(list, () => list.actions.deleteSelectedRules()).toFinishAllListeners()
            }

            expect(options.values.issueTag).toBeNull()
        }
    )
})
