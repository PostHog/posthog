import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonTabs } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { inboxSceneLogic } from '../../inboxSceneLogic'
import { INBOX_TAB_KEYS, INBOX_TAB_LABEL, InboxTabKey } from '../../types'

/** Synthetic key for the onboarding "Welcome" tab – presentational only, never routed to. */
const WELCOME_TAB_KEY = 'welcome'

type InboxTabBarKey = InboxTabKey | typeof WELCOME_TAB_KEY

/**
 * Page tab bar: Reports / Scouts / Settings. The report sections (Review and merge / Needs a PR /
 * Resolved) live inside the Reports tab, so no counts sit here.
 *
 * In `onboarding` mode (self-driving not set up, empty inbox) a locked "Welcome" tab is shown and
 * selected, while the real tabs stay visible but disabled – the user can see what's coming, but the
 * inbox only opens up once self-driving is set up.
 */
export function InboxTabBar({ onboarding }: { onboarding?: boolean }): JSX.Element {
    const { activeTab } = useValues(inboxSceneLogic)

    const realTabs = INBOX_TAB_KEYS.map((key) => ({
        key: key as InboxTabBarKey,
        label: INBOX_TAB_LABEL[key],
        disabledReason: onboarding ? 'Set up self-driving to open your inbox' : undefined,
        content: <></>,
    }))

    const tabs = onboarding
        ? [{ key: WELCOME_TAB_KEY as InboxTabBarKey, label: 'Welcome', content: <></> }, ...realTabs]
        : realTabs

    return (
        <LemonTabs<InboxTabBarKey>
            activeKey={onboarding ? WELCOME_TAB_KEY : activeTab}
            // min-w-0 lets the tab bar shrink inside the header row so its own overflow-x scroll
            // engages on narrow/mobile widths instead of the last tabs overflowing off-screen.
            className="min-w-0"
            // Hide LemonTabs' own bottom border + margin so the single full-width border lives on the
            // scene header row; the active-tab slider then sits directly on that one border.
            barClassName="before:hidden mb-0"
            onChange={(key) => {
                if (key !== WELCOME_TAB_KEY) {
                    router.actions.push(urls.inbox(key))
                }
            }}
            tabs={tabs}
            data-attr="inbox-tabs"
        />
    )
}
