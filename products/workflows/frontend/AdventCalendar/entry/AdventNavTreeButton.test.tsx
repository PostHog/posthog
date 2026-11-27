import { act, render, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { CategorySuffixNav, CustomCategorySuffix } from '~/layout/panel-layout/ProjectTree/customCategorySuffixRegistry'
import { ProductItemCategory } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

const TREE_LABEL = 'Open the Workflows advent calendar'
const NAVS: CategorySuffixNav[] = ['classic', 'today']

function preferReducedMotion(reduce: boolean): void {
    jest.spyOn(window, 'matchMedia').mockImplementation(
        (query: string) => ({ matches: reduce && query.includes('reduce'), media: query }) as MediaQueryList
    )
}

async function findTree(container: HTMLElement): Promise<HTMLElement> {
    return await within(container).findByLabelText(TREE_LABEL, {}, { timeout: 5000 })
}

async function settleLazyImports(): Promise<void> {
    await act(() => new Promise((resolve) => setTimeout(resolve, 0)))
}

describe('the advent tree on the Messaging sidebar header', () => {
    let captured: [string, unknown][]

    beforeEach(() => {
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
        document.querySelector('.AdventHoverSnow')?.remove()
        jest.restoreAllMocks()
    })

    it.each(NAVS)('the %s nav links the tree to the calendar and reports the click', async (nav) => {
        const { container } = render(<CustomCategorySuffix category={ProductItemCategory.MESSAGING} nav={nav} />)

        const tree = await findTree(container)
        expect(tree.closest('a')?.getAttribute('href')).toContain(urls.workflowsAdventCalendar())

        await userEvent.click(tree)
        expect(captured).toEqual([['workflows advent entry clicked', { entry: 'nav-tree', nav }]])
    })

    it.each<[string, string, boolean]>([
        ['another category', ProductItemCategory.ANALYTICS, true],
        ['Messaging with the flag off', ProductItemCategory.MESSAGING, false],
    ])('shows no tree on %s', async (_, category, flagOn) => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_ADVENT_CALENDAR]: flagOn })

        const { container } = render(
            <>
                {NAVS.map((nav) => (
                    <CustomCategorySuffix key={nav} category={category} nav={nav} />
                ))}
            </>
        )
        await settleLazyImports()

        expect(container.innerHTML).toEqual('')
    })

    it.each(NAVS)('hovering the %s tree lets snow fall until the pointer leaves', async (nav) => {
        const { container } = render(<CustomCategorySuffix category={ProductItemCategory.MESSAGING} nav={nav} />)
        const tree = await findTree(container)

        await userEvent.hover(tree)
        await waitFor(() => expect(document.querySelector('.AdventHoverSnow--falling')).not.toBeNull())

        await userEvent.unhover(tree)
        await settleLazyImports()
        expect(document.querySelector('.AdventHoverSnow--falling')).toBeNull()
    })

    it('lets no snow fall for a person who prefers reduced motion', async () => {
        preferReducedMotion(true)
        const { container } = render(<CustomCategorySuffix category={ProductItemCategory.MESSAGING} nav="classic" />)

        await userEvent.hover(await findTree(container))
        await settleLazyImports()

        expect(document.querySelector('.AdventHoverSnow')).toBeNull()
    })
})
