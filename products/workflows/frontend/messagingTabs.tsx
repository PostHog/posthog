import { MessageChannels } from './Channels/MessageChannels'
import { OptOutScene } from './OptOuts/OptOutScene'
import { SuppressionScene } from './Suppression/SuppressionScene'
import { MessageTemplatesTable } from './TemplateLibrary/MessageTemplatesTable'
import { WorkflowsReputation } from './Workflows/Reputation/WorkflowsReputation'

// pinned: URL path segments under /workflows and /broadcasts - renaming breaks bookmarks
export const MESSAGING_NAV_TAB_KEYS = ['library', 'channels', 'opt-outs', 'suppression', 'reputation'] as const
export type MessagingNavTabKey = (typeof MESSAGING_NAV_TAB_KEYS)[number]

/** The tabs that configure sending, grouped under one "Messaging" tab. */
export const MESSAGING_SETUP_TAB_KEYS = ['channels', 'opt-outs', 'suppression', 'reputation'] as const
export type MessagingSetupTabKey = (typeof MESSAGING_SETUP_TAB_KEYS)[number]

export const MESSAGING_TAB_LABELS: Record<MessagingNavTabKey, string> = {
    library: 'Library',
    channels: 'Channels',
    'opt-outs': 'Opt-outs',
    suppression: 'Suppression list',
    reputation: 'Reputation',
}

export const MESSAGING_TAB_CONTENT: Record<MessagingNavTabKey, JSX.Element> = {
    library: <MessageTemplatesTable />,
    channels: <MessageChannels />,
    'opt-outs': <OptOutScene />,
    suppression: <SuppressionScene />,
    reputation: <WorkflowsReputation />,
}

export function isMessagingSetupTab(tab: string): tab is MessagingSetupTabKey {
    return (MESSAGING_SETUP_TAB_KEYS as readonly string[]).includes(tab)
}
