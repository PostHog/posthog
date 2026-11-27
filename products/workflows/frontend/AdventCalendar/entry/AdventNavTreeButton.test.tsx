import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { CategorySuffixNav, CustomCategorySuffix } from '~/layout/panel-layout/ProjectTree/CustomCategorySuffix'
import { ProductItemCategory } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

const TREE_LABEL = 'Open the Workflows advent calendar'
const NAVS: CategorySuffixNav[] = ['classic', 'today']

type OpenTheTree = (tree: HTMLElement) => void

const OPENINGS: [string, OpenTheTree][] = [
    ['a click', (tree) => fireEvent.click(tree)],
    ['a Cmd-click', (tree) => fireEvent.click(tree, { metaKey: true })],
    ['a Ctrl-click', (tree) => fireEvent.click(tree, { ctrlKey: true })],
    ['a middle click', (tree) => fireEvent(tree, new MouseEvent('auxclick', { bubbles: true, button: 1 }))],
]

function preferReducedMotion(reduce: boolean): void {
    jest.spyOn(window, 'matchMedia').mockImplementation(
        (query: string) => ({ matches: reduce && query.includes('reduce'), media: query }) as MediaQueryList
    )
}

function renderMessagingHeader(nav: CategorySuffixNav, category: string = ProductItemCategory.MESSAGING): HTMLElement {
    return render(<CustomCategorySuffix category={category} nav={nav} />).container
}

async function findTree(container: HTMLElement): Promise<HTMLElement> {
    return await within(container).findByLabelText(TREE_LABEL)
}

async function runPendingWork(): Promise<void> {
    await act(() => jest.runAllTimersAsync())
}

function snowFalls(): boolean {
    return document.querySelector('.AdventHoverSnow--falling') !== null
}

describe('the advent tree on the Messaging sidebar header', () => {
    let captured: [string, unknown][]

    beforeEach(() => {
        jest.useFakeTimers()
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_ADVENT_CALENDAR]: true })
        captured = []
        jest.spyOn(posthog, 'capture').mockImplementation((event, properties) => {
            captured.push([event, properties])
            return undefined
        })
        preferReducedMotion(false)
    })

    afterEach(() => {
        cleanup()
        document.querySelector('.AdventHoverSnow')?.remove()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it.each(NAVS)('the %s nav links the tree to the calendar', async (nav) => {
        const tree = await findTree(renderMessagingHeader(nav))

        expect(tree.closest('a')?.getAttribute('href')).toContain(urls.workflowsAdventCalendar())
    })

    it.each(NAVS.flatMap((nav) => OPENINGS.map(([how, open]) => [nav, how, open] as const)))(
        'the %s nav reports %s on the tree once',
        async (nav, _how, open) => {
            const tree = await findTree(renderMessagingHeader(nav))

            open(tree)

            expect(captured.filter(([event]) => event.startsWith('workflows advent'))).toEqual([
                ['workflows advent entry clicked', { entry: 'nav-tree', nav, has_workflows: null }],
            ])
        }
    )

    it.each<[string, string, boolean]>([
        ['another category', ProductItemCategory.ANALYTICS, true],
        ['Messaging with the flag off', ProductItemCategory.MESSAGING, false],
    ])('shows no tree on %s', async (_, category, flagOn) => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_ADVENT_CALENDAR]: flagOn })

        for (const nav of NAVS) {
            renderMessagingHeader(nav, category)
        }
        await runPendingWork()

        expect(screen.queryByLabelText(TREE_LABEL)).toBeNull()
    })

    it.each(NAVS)('hovering the %s tree lets snow fall until the pointer leaves', async (nav) => {
        const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime })
        const tree = await findTree(renderMessagingHeader(nav))

        await user.hover(tree)
        await runPendingWork()
        expect(snowFalls()).toBe(true)

        await user.unhover(tree)
        await runPendingWork()
        expect(snowFalls()).toBe(false)
    })

    it('pointing at the open tooltip of the today tree lets no snow fall', async () => {
        const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime })
        const tree = await findTree(renderMessagingHeader('today'))

        await user.tab()
        expect(document.activeElement).toBe(tree)
        await runPendingWork()
        await user.hover(await screen.findByText(TREE_LABEL))
        await runPendingWork()

        expect(snowFalls()).toBe(false)
    })

    it('lets no snow fall for a person who prefers reduced motion', async () => {
        preferReducedMotion(true)
        const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime })

        await user.hover(await findTree(renderMessagingHeader('classic')))
        await runPendingWork()

        expect(document.querySelector('.AdventHoverSnow')).toBeNull()
    })
})
