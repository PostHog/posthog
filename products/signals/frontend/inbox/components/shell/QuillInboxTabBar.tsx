import { useValues } from 'kea'
import { router } from 'kea-router'

import { Tabs, TabsList, TabsTrigger } from '@posthog/quill'

import { urls } from 'scenes/urls'

import { inboxSceneLogic } from '../../inboxSceneLogic'
import { INBOX_TAB_KEYS, INBOX_TAB_LABEL, InboxTabKey } from '../../types'

/** The quill sibling of `InboxTabBar`. Each tab is a URL, so a change pushes the route rather than local state. */
export function QuillInboxTabBar(): JSX.Element {
    const { activeTab } = useValues(inboxSceneLogic)

    return (
        <Tabs
            data-quill
            value={activeTab}
            onValueChange={(key) => router.actions.push(urls.inbox(key as InboxTabKey))}
            // min-w-0 lets the bar shrink inside the header row, so it scrolls sideways on a phone instead of
            // pushing the last tabs off-screen.
            className="min-w-0 overflow-x-auto"
            data-attr="inbox-tabs"
        >
            <TabsList variant="line">
                {INBOX_TAB_KEYS.map((key) => (
                    <TabsTrigger key={key} value={key}>
                        {INBOX_TAB_LABEL[key]}
                    </TabsTrigger>
                ))}
            </TabsList>
        </Tabs>
    )
}
