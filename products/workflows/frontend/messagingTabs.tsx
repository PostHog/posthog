import { LemonTag } from '@posthog/lemon-ui'

import { LemonTab } from 'lib/lemon-ui/LemonTabs'
import { urls } from 'scenes/urls'

/**
 * Sending setup that every messaging surface shares: templates, senders, and who may be sent to.
 * Workflows renders these with their content; Broadcasts renders them as links back to it, so a
 * sender or a suppression rule is one click away from either surface rather than only from one.
 */
export type MessagingNavTabKey = 'library' | 'channels' | 'opt-outs' | 'suppression' | 'reputation'

export function messagingNavTabs(): LemonTab<MessagingNavTabKey>[] {
    return [
        { label: 'Library', key: 'library', link: urls.workflows('library') },
        { label: 'Channels', key: 'channels', link: urls.workflows('channels') },
        { label: 'Opt-outs', key: 'opt-outs', link: urls.workflows('opt-outs') },
        { label: 'Suppression list', key: 'suppression', link: urls.workflows('suppression') },
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
            link: urls.workflows('reputation'),
        },
    ]
}
