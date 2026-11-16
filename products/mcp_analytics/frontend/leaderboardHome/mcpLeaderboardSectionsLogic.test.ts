import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { LeaderboardSectionId } from './leaderboardSections'
import { mcpLeaderboardSectionsLogic } from './mcpLeaderboardSectionsLogic'

describe('mcpLeaderboardSectionsLogic', () => {
    let logic: ReturnType<typeof mcpLeaderboardSectionsLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        localStorage.clear()
        initKeaTests()
    })

    function mountLogic(): void {
        logic = mcpLeaderboardSectionsLogic()
        logic.mount()
    }

    it('shows every section by default', () => {
        mountLogic()

        expect(logic.values.hiddenSections).toEqual([])
    })

    it.each<{ toggles: LeaderboardSectionId[]; hidden: LeaderboardSectionId[] }>([
        { toggles: ['models'], hidden: ['models'] },
        { toggles: ['models', 'models'], hidden: [] },
        { toggles: ['reliability', 'key-metrics'], hidden: ['key-metrics', 'reliability'] },
    ])('toggling $toggles leaves $hidden hidden', ({ toggles, hidden }) => {
        mountLogic()

        toggles.forEach((id) => logic.actions.toggleSection(id))

        expectLogic(logic).toMatchValues({ hiddenSections: hidden })
        expect(logic.values.isSectionVisible('key-metrics')).toBe(!hidden.includes('key-metrics'))
        expect(logic.values.isSectionVisible('models')).toBe(!hidden.includes('models'))
    })

    it('showAllSections clears every hidden section', () => {
        mountLogic()
        logic.actions.toggleSection('protocol')
        logic.actions.toggleSection('agents')

        logic.actions.showAllSections()

        expectLogic(logic).toMatchValues({ hiddenSections: [] })
        expect(posthog.capture).toHaveBeenLastCalledWith('mcp analytics dashboard sections reset', {
            hidden_count: 2,
        })
    })

    it('reports each toggle with the resulting hidden state', () => {
        mountLogic()
        jest.mocked(posthog.capture).mockClear()

        logic.actions.toggleSection('protocol')
        logic.actions.toggleSection('protocol')

        expect(posthog.capture).toHaveBeenNthCalledWith(1, 'mcp analytics dashboard section toggled', {
            section: 'protocol',
            hidden: true,
        })
        expect(posthog.capture).toHaveBeenNthCalledWith(2, 'mcp analytics dashboard section toggled', {
            section: 'protocol',
            hidden: false,
        })
    })

    it('restores hidden sections from storage, ignores ids of removed sections, and reports them on view', () => {
        mountLogic()
        logic.actions.toggleSection('models')
        const storageKey = Object.keys(localStorage).find((key) => key.endsWith('.hiddenSectionIds'))!
        expect(JSON.parse(localStorage.getItem(storageKey)!)).toEqual(['models'])
        localStorage.setItem(storageKey, JSON.stringify(['models', 'retired-section']))
        initKeaTests()

        mountLogic()

        expectLogic(logic).toMatchValues({ hiddenSections: ['models'] })
        expect(logic.values.isSectionVisible('models')).toBe(false)
        expect(logic.values.isSectionVisible('protocol')).toBe(true)
        expect(posthog.capture).toHaveBeenLastCalledWith('mcp analytics dashboard viewed', {
            hidden_sections: ['models'],
            hidden_count: 1,
        })
    })
})
