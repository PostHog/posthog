import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { McpDashboardCardId } from './dashboardCards'
import { mcpDashboardCardsLogic } from './mcpDashboardCardsLogic'

jest.mock('posthog-js', () => ({ __esModule: true, default: { capture: jest.fn() } }))

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

        expectLogic(logic).toMatchValues({ hiddenCardIds: [], hiddenCount: 0 })
    })

    it.each<{ toggles: McpDashboardCardId[]; hidden: McpDashboardCardId[] }>([
        { toggles: ['model'], hidden: ['model'] },
        { toggles: ['model', 'model'], hidden: [] },
        { toggles: ['recent-activity', 'kpis'], hidden: ['recent-activity', 'kpis'] },
    ])('toggling $toggles leaves $hidden hidden', ({ toggles, hidden }) => {
        mountLogic()

        toggles.forEach((id) => logic.actions.toggleCard(id))

        expectLogic(logic).toMatchValues({ hiddenCardIds: hidden, hiddenCount: hidden.length })
        expect(logic.values.isCardVisible('kpis')).toBe(!hidden.includes('kpis'))
        expect(logic.values.isCardVisible('model')).toBe(!hidden.includes('model'))
    })

    it('showAllCards clears every hidden card', () => {
        mountLogic()
        logic.actions.toggleCard('harness')
        logic.actions.toggleCard('tool-errors')

        logic.actions.showAllCards()

        expectLogic(logic).toMatchValues({ hiddenCardIds: [], hiddenCount: 0 })
    })

    it('reports each toggle with the resulting hidden state', () => {
        mountLogic()

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

    it('restores hidden cards from storage and ignores ids of removed cards', () => {
        mountLogic()
        logic.actions.toggleCard('model')
        const storageKey = Object.keys(localStorage).find((key) => key.endsWith('.hiddenCardIds'))!
        expect(JSON.parse(localStorage.getItem(storageKey)!)).toEqual(['model'])
        localStorage.setItem(storageKey, JSON.stringify(['model', 'retired-card']))
        initKeaTests()

        mountLogic()

        expectLogic(logic).toMatchValues({ hiddenCount: 1 })
        expect(logic.values.isCardVisible('model')).toBe(false)
        expect(logic.values.isCardVisible('harness')).toBe(true)
    })
})
