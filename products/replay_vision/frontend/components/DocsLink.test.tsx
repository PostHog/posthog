import { cleanup, render, within } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { VisionDocsLink } from './DocsLink'

// Every replay vision empty-state docs link flows through VisionDocsLink, so one test on the URL
// template guards all surfaces against a broken base URL, page join, utm params, or target.
describe('VisionDocsLink', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        [undefined, 'https://posthog.com/docs/replay-vision?utm_medium=in-product&utm_campaign=empty-state-docs-link'],
        [
            'creating-scanners',
            'https://posthog.com/docs/replay-vision/creating-scanners?utm_medium=in-product&utm_campaign=empty-state-docs-link',
        ],
    ])('renders a new-tab docs anchor for page %s', (page, expectedHref) => {
        const { container } = render(
            <VisionDocsLink page={page} dataAttr="vision-empty-docs-link-test">
                Learn more
            </VisionDocsLink>
        )
        const anchor = within(container).getByText('Learn more').closest('a')
        expect(anchor?.getAttribute('href')).toBe(expectedHref)
        expect(anchor?.getAttribute('target')).toBe('_blank')
        expect(anchor?.getAttribute('data-attr')).toBe('vision-empty-docs-link-test')
    })
})
