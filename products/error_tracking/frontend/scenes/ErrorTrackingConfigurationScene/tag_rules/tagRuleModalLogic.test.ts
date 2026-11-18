import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import type { MouseEvent } from 'react'

import { LemonDialog } from '@posthog/lemon-ui'

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

    // An edit that changes which properties the filters read makes the backend delete every tag the rule applied.
    it.each([
        ['saves an edit to a filter value at once', { ...browserFilter, value: ['Chrome'] }, 0],
        ['asks before an edit to a filter property removes the existing tags', { ...browserFilter, key: '$os' }, 1],
    ])('%s', async (_, filter, dialogs) => {
        const confirm = jest.spyOn(LemonDialog, 'open').mockImplementation(() => {})
        const logic = tagRuleModalLogic()
        logic.mount()
        const filters = { type: FilterLogicalOperator.And, values: [filter] }

        logic.actions.openModal(persistedRule)
        logic.actions.updateRule({ ...persistedRule, filters })
        await expectLogic(logic, () => logic.actions.saveRule()).toFinishAllListeners()

        expect(requests).toHaveLength(1 - dialogs)
        confirm.mock.calls.forEach(([dialog]) => dialog.primaryButton?.onClick?.({} as MouseEvent<HTMLButtonElement>))
        await expectLogic(logic).toFinishAllListeners()
        expect(requests).toEqual([
            {
                method: 'PUT',
                path: `${TAG_RULES_PATH}${persistedRule.id}/`,
                body: { label: persistedRule.label, description: persistedRule.description, filters },
            },
        ])
        confirm.mockRestore()
    })

    // A rule reads only the first exception of a new issue. A preview that counts every matching exception counts
    // issues that the rule never labels.
    it('previews the first exception of each issue first seen in the selected window', async () => {
        let sentQuery: unknown = null
        const recordQuery = async ({ request }: MockResolverInfo): Promise<Record<string, unknown>> => {
            sentQuery = ((await request.json()) as { query: unknown }).query
            return { results: [[2, 2]] }
        }
        useMocks({
            post: {
                '/api/projects/:team_id/query/:kind/': recordQuery,
                '/api/environments/:team_id/query/:kind/': recordQuery,
            },
        })
        const logic = tagRuleModalLogic()
        logic.mount()

        logic.actions.openModal(persistedRule)
        await expectLogic(logic, () => logic.actions.increaseDateRange()).toFinishAllListeners()

        expect(sentQuery).toMatchObject({
            after: '-30d',
            where: [
                expect.stringMatching(
                    /argMin\(uuid, timestamp\).*HAVING min\(first_seen\) >= now\(\) - INTERVAL 30 DAY/
                ),
            ],
        })
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

    // A bulk delete that rejects as a whole keeps the deleted rules in the list, so a retry hits their 404s, and the
    // issue list keeps a filter on a label that is gone.
    it('removes the deleted rules and keeps the failed one when part of a bulk delete fails', async () => {
        const deletedRule = { ...persistedRule, disabled_data: null }
        const failingRule = { ...deletedRule, id: 'failing-rule-id', key: 'rule_4567', label: 'Safari' }
        rules = [deletedRule, failingRule]
        useMocks({
            delete: {
                '/api/projects/:team_id/error_tracking/tag_rules/:id/': ({ params }) => {
                    if (params.id === failingRule.id) {
                        return [500]
                    }
                    rules = rules.filter((rule) => rule.id !== params.id)
                    return [204]
                },
            },
        })
        const options = issueQueryOptionsLogic({ logicKey: 'test' })
        options.mount()
        await expectLogic(issueTagDefinitionsLogic, () => {
            issueTagDefinitionsLogic.mount()
        }).toFinishAllListeners()
        options.actions.setIssueTag({ key: deletedRule.key, applied: true })
        tagRuleModalLogic.mount()
        const list = rulesLogic({ ruleType: ErrorTrackingRuleType.Tag })
        await expectLogic(list, () => list.actions.loadRules()).toFinishAllListeners()

        list.actions.startSelectingRules()
        list.actions.setSelectedRuleIds([deletedRule.id, failingRule.id])
        await expectLogic(list, () => list.actions.deleteSelectedRules()).toFinishAllListeners()

        expect(list.values.rules.map((rule) => rule.id)).toEqual([failingRule.id])
        expect(options.values.issueTag).toBeNull()
    })

    // Cancel clears the selection while the deletes run. Reading the selection after them treats every delete as failed.
    it('removes deleted rules when the selection is cancelled while the deletes run', async () => {
        const deletedRule = { ...persistedRule, disabled_data: null }
        rules = [deletedRule]
        let releaseDelete: () => void = () => {}
        const deleteGate = new Promise<void>((resolve) => {
            releaseDelete = resolve
        })
        useMocks({
            delete: {
                '/api/projects/:team_id/error_tracking/tag_rules/:id/': async ({ params }) => {
                    await deleteGate
                    rules = rules.filter((rule) => rule.id !== params.id)
                    return [204]
                },
            },
        })
        tagRuleModalLogic.mount()
        const list = rulesLogic({ ruleType: ErrorTrackingRuleType.Tag })
        await expectLogic(list, () => list.actions.loadRules()).toFinishAllListeners()

        list.actions.startSelectingRules()
        list.actions.setSelectedRuleIds([deletedRule.id])
        list.actions.deleteSelectedRules()
        list.actions.cancelSelectingRules()
        releaseDelete()
        await expectLogic(list).toFinishAllListeners()

        expect(list.values.rules).toEqual([])
    })
})
