import type { MessagingNavTabKey } from './messagingTabs'
import { QuillNewCategoryButton } from './QuillNewCategoryButton'
import { QuillNewChannelButton } from './QuillNewChannelButton'
import { QuillNewTemplateButton } from './QuillNewTemplateButton'

export function QuillMessagingTabActions({
    tab,
    channelsUrl,
}: {
    tab: MessagingNavTabKey
    channelsUrl: string
}): JSX.Element | null {
    // One component per action, so a tab mounts (and loads) only the logic its own button needs.
    if (tab === 'library') {
        return <QuillNewTemplateButton />
    }
    if (tab === 'channels') {
        return <QuillNewChannelButton channelsUrl={channelsUrl} />
    }
    if (tab === 'opt-outs') {
        return <QuillNewCategoryButton />
    }
    return null
}
