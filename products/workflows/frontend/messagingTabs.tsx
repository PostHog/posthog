import { LemonTag } from '@posthog/lemon-ui'

import { LemonTab } from 'lib/lemon-ui/LemonTabs'

import { MessageChannels } from './Channels/MessageChannels'
import { OptOutScene } from './OptOuts/OptOutScene'
import { SuppressionScene } from './Suppression/SuppressionScene'
import { MessageTemplatesTable } from './TemplateLibrary/MessageTemplatesTable'
import { WorkflowsReputation } from './Workflows/Reputation/WorkflowsReputation'

// pinned: URL path segments under /workflows and /broadcasts - renaming breaks bookmarks
export const MESSAGING_NAV_TAB_KEYS = ['library', 'channels', 'opt-outs', 'suppression', 'reputation'] as const
export type MessagingNavTabKey = (typeof MESSAGING_NAV_TAB_KEYS)[number]

export const MESSAGING_TAB_CONTENT: Record<MessagingNavTabKey, JSX.Element> = {
    library: <MessageTemplatesTable />,
    channels: <MessageChannels />,
    'opt-outs': <OptOutScene />,
    suppression: <SuppressionScene />,
    reputation: <WorkflowsReputation />,
}

/**
 * Sending setup that every messaging surface shares: templates, senders, and who may be sent to.
 * Each surface renders them under its own URL, so switching tabs never leaves the surface.
 */
export function messagingNavTabs(linkFor: (tab: MessagingNavTabKey) => string): LemonTab<MessagingNavTabKey>[] {
    return [
        { label: 'Library', key: 'library', link: linkFor('library'), content: MESSAGING_TAB_CONTENT.library },
        { label: 'Channels', key: 'channels', link: linkFor('channels'), content: MESSAGING_TAB_CONTENT.channels },
        {
            label: 'Opt-outs',
            key: 'opt-outs',
            link: linkFor('opt-outs'),
            content: MESSAGING_TAB_CONTENT['opt-outs'],
        },
        {
            label: 'Suppression list',
            key: 'suppression',
            link: linkFor('suppression'),
            content: MESSAGING_TAB_CONTENT.suppression,
        },
        {
            label: (
                <>
                    Reputation{' '}
                    <LemonTag className="ml-1" type="completion">
                        Beta
                    </LemonTag>
                </>
            ),
            key: 'reputation',
            link: linkFor('reputation'),
            content: MESSAGING_TAB_CONTENT.reputation,
        },
    ]
}
