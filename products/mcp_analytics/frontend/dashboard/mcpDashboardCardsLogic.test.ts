import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { McpDashboardCardId } from './dashboardCards'
import { mcpDashboardCardsLogic } from './mcpDashboardCardsLogic'

describe('mcpDashboardCardsLogic', () => {
    let logic: ReturnType<typeof mcpDashboardCardsLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        localStorage.clear()
        initKeaTests()
    })

    function mountLogic(): void {
        logic = mcpDashboardCardsLogic()
        logic.mount()
    }

    it('shows every card by default', () => {
        mountLogic()

        expectLogic(logic).toMatchValues({ hiddenCards: [] })
    })

    it.each<{ toggles: McpDashboardCardId[]; hidden: McpDashboardCardId[] }>([
        { toggles: ['model'], hidden: ['model'] },
        { toggles: ['model', 'model'], hidden: [] },
        { toggles: ['recent-activity', 'kpis'], hidden: ['kpis', 'recent-activity'] },
    ])('toggling $toggles leaves $hidden hidden', ({ toggles, hidden }) => {
        mountLogic()

        toggles.forEach((id) => logic.actions.toggleCard(id))

        expectLogic(logic).toMatchValues({ hiddenCards: hidden })
        expect(logic.values.isCardVisible('kpis')).toBe(!hidden.includes('kpis'))
        expect(logic.values.isCardVisible('model')).toBe(!hidden.includes('model'))
    })

    it('showAllCards clears every hidden card', () => {
        mountLogic()
        logic.actions.toggleCard('harness')
        logic.actions.toggleCard('tool-errors')

        logic.actions.showAllCards()

        expectLogic(logic).toMatchValues({ hiddenCards: [] })
        expect(posthog.capture).toHaveBeenLastCalledWith('mcp analytics dashboard cards reset', { hidden_count: 2 })
    })

    it('reports each toggle with the resulting hidden state', () => {
        mountLogic()
        jest.mocked(posthog.capture).mockClear()

        logic.actions.toggleCard('harness')
        logic.actions.toggleCard('harness')

        expect(posthog.capture).toHaveBeenNthCalledWith(1, 'mcp analytics dashboard card toggled', {
            card: 'harness',
            hidden: true,
        })
        expect(posthog.capture).toHaveBeenNthCalledWith(2, 'mcp analytics dashboard card toggled', {
            card: 'harness',
            hidden: false,
        })
    })

    it('restores hidden cards from storage, ignores ids of removed cards, and reports them on view', () => {
        mountLogic()
        logic.actions.toggleCard('model')
        const storageKey = Object.keys(localStorage).find((key) => key.endsWith('.hiddenCardIds'))!
        expect(JSON.parse(localStorage.getItem(storageKey)!)).toEqual(['model'])
        localStorage.setItem(storageKey, JSON.stringify(['model', 'retired-card']))
        initKeaTests()

        mountLogic()

        expectLogic(logic).toMatchValues({ hiddenCards: ['model'] })
        expect(logic.values.isCardVisible('model')).toBe(false)
        expect(logic.values.isCardVisible('harness')).toBe(true)
        expect(posthog.capture).toHaveBeenLastCalledWith('mcp analytics dashboard viewed', {
            hidden_cards: ['model'],
            hidden_count: 1,
        })
    })
})
