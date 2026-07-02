/** UX-overhaul preview: five faked pages behind local-state navigation. The point is to feel the
 *  proposed information architecture — one entity skeleton per level (repo → workflow → run / PR →
 *  author), one scope bar, one section rhythm — before wiring anything to the backend. */

import { LemonBanner } from '@posthog/lemon-ui'

import { MockAuthorPage, MockPrPage, MockRunPage } from './MockDetailPages'
import { MockAuthorListPage, MockPrListPage } from './MockListPages'
import { MockRepoHub } from './MockRepoHub'
import { MockWorkflowPage } from './MockWorkflowPage'
import { MockNavProvider, useMockNav } from './shared'

function MockRouter(): JSX.Element {
    const { route } = useMockNav()
    switch (route.page) {
        case 'workflow':
            return <MockWorkflowPage slug={route.slug} />
        case 'run':
            return <MockRunPage id={route.id} />
        case 'pr':
            return <MockPrPage number={route.number} />
        case 'author':
            return <MockAuthorPage handle={route.handle} />
        case 'prList':
            return <MockPrListPage />
        case 'authorList':
            return <MockAuthorListPage />
        case 'repo':
        default:
            return <MockRepoHub />
    }
}

export function MockUxPreview(): JSX.Element {
    return (
        <div className="MockUxPreview">
            <LemonBanner type="warning" className="mt-2">
                UX overhaul preview — every number on these pages is faked and navigation is internal to this tab.
                Nothing calls the backend.
            </LemonBanner>
            <MockNavProvider>
                <MockRouter />
            </MockNavProvider>
        </div>
    )
}

export default MockUxPreview
