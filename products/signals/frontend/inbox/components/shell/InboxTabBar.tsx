import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonTabs } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { inboxSceneLogic } from '../../inboxSceneLogic'
import { INBOX_TAB_KEYS, INBOX_TAB_LABEL, InboxTabKey } from '../../types'

/**
 * Page tab bar: Reports / Scouts / Settings. The report sections (Review and merge / Needs a PR /
 * Resolved) live inside the Reports tab, so no counts sit here.
 */
export function InboxTabBar(): JSX.Element {
    const { activeTab } = useValues(inboxSceneLogic)

    const tabs = INBOX_TAB_KEYS.map((key) => ({
        key,
        label: INBOX_TAB_LABEL[key],
        content: <></>,
    }))

    return (
        <LemonTabs<InboxTabKey>
            activeKey={activeTab}
            // min-w-0 lets the tab bar shrink inside the header row so its own overflow-x scroll
            // engages on narrow/mobile widths instead of the last tabs overflowing off-screen.
            className="min-w-0"
            // Hide LemonTabs' own bottom border + margin so the single full-width border lives on the
            // scene header row; the active-tab slider then sits directly on that one border.
            barClassName="before:hidden mb-0"
            onChange={(key) => router.actions.push(urls.inbox(key))}
            tabs={tabs}
            data-attr="inbox-tabs"
        />
    )
}
