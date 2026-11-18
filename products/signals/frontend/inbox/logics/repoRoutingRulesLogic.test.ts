/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { RepoRoutingRuleApi } from 'products/tasks/frontend/generated/api.schemas'

import { MAX_RULES_PER_TEAM, repoRoutingRulesLogic } from './repoRoutingRulesLogic'

function rule(id: string, ruleText: string, repository: string, priority: number): RepoRoutingRuleApi {
    return {
        id,
        rule_text: ruleText,
        repository,
        priority,
        created_by: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
    }
}

const EXISTING = rule('rule-1', 'anything about the docs', 'posthog/posthog.com', 0)
const CREATED = rule('rule-2', 'the support dashboard', 'posthog/posthog-android', 1)
const UPDATED = rule('rule-1', 'docs and the marketing site', 'posthog/posthog.com', 0)

describe('repoRoutingRulesLogic', () => {
    let logic: ReturnType<typeof repoRoutingRulesLogic.build> | undefined

    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: { '/api/projects/:team_id/tasks/repo_routing_rules/': [EXISTING] },
            post: { '/api/projects/:team_id/tasks/repo_routing_rules/': [201, CREATED] },
            patch: { '/api/projects/:team_id/tasks/repo_routing_rules/:id/': [200, UPDATED] },
            delete: { '/api/projects/:team_id/tasks/repo_routing_rules/:id/': [204, null] },
        })
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('keeps the list in sync through add, edit, and remove', async () => {
        logic = repoRoutingRulesLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.rules).toEqual([EXISTING])

        logic.actions.setDraftRuleText('the support dashboard')
        logic.actions.setDraftRepository('posthog/posthog-android')
        logic.actions.addRule()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.rules).toEqual([EXISTING, CREATED])
        // Cleared drafts keep a second click from re-posting the same rule.
        expect(logic.values.draftRuleText).toEqual('')
        expect(logic.values.draftRepository).toEqual('')

        logic.actions.startEditingRule(EXISTING, null)
        expect(logic.values.editRuleText).toEqual(EXISTING.rule_text)
        logic.actions.setEditRuleText('docs and the marketing site')
        logic.actions.saveEditedRule()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.rules).toEqual([UPDATED, CREATED])
        expect(logic.values.editingRuleId).toBeNull()

        logic.actions.deleteRule(CREATED)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.rules).toEqual([UPDATED])
    })

    it('clears the picked repository when the GitHub org changes', () => {
        logic = repoRoutingRulesLogic()
        logic.mount()
        logic.actions.setDraftRepository('posthog/posthog.com')
        logic.actions.setDraftIntegrationId(2)
        expect(logic.values.draftRepository).toEqual('')

        logic.actions.startEditingRule(EXISTING, 1)
        logic.actions.setEditIntegrationId(2)
        expect(logic.values.editRepository).toEqual('')
    })

    it('gates the add button once the team hits the rule cap', async () => {
        const fullSet = Array.from({ length: MAX_RULES_PER_TEAM }, (_, i) =>
            rule(`rule-${i}`, `rule ${i}`, 'posthog/posthog.com', i)
        )
        useMocks({ get: { '/api/projects/:team_id/tasks/repo_routing_rules/': fullSet } })
        logic = repoRoutingRulesLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setDraftRuleText('one too many')
        logic.actions.setDraftRepository('posthog/posthog.com')
        expect(logic.values.addRuleDisabledReason).toContain(`${MAX_RULES_PER_TEAM}`)
    })

    it.each([
        ['', 'posthog/posthog-android', 'Describe which requests the rule matches'],
        ['x'.repeat(301), 'posthog/posthog-android', 'Keep the rule under 300 characters'],
        ['the support dashboard', '', 'Pick a repository'],
        ['the support dashboard', 'posthog/posthog-android', null],
    ])('gates the add button on draft validity (%#)', (ruleText, repository, reason) => {
        logic = repoRoutingRulesLogic()
        logic.mount()
        logic.actions.setDraftRuleText(ruleText)
        logic.actions.setDraftRepository(repository)
        expect(logic.values.addRuleDisabledReason).toEqual(reason)
    })
})
