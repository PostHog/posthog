import { useRouter } from 'expo-router'
import type { ReactElement } from 'react'

import { useInboxHasUnread } from '@/features/inbox/useInboxHasUnread'
import { useMobileProductFlags } from '@/lib/featureFlags'
import { BottomBar } from './BottomBar'
import { openNavTarget } from './navPinRoutes'
import { useNavPins } from './navPinStore'
import { navPinEnabled } from './visibleNavPins'

/** A report opens from the inbox, so the bar beside it selects Inbox. */
export function ReportNavigation(): ReactElement {
    const router = useRouter()
    const pins = useNavPins()
    const flags = useMobileProductFlags()
    const inboxUnread = useInboxHasUnread()
    return (
        <BottomBar
            selected="inbox"
            pins={pins.filter((pin) => navPinEnabled(pin, flags))}
            inboxUnread={inboxUnread}
            onHome={() => router.navigate('/live')}
            onInbox={() => router.navigate('/inbox')}
            onChats={() => router.navigate('/chats')}
            onViews={() => router.navigate('/views')}
            onPin={(pin) => openNavTarget(router, pin, true)}
        />
    )
}
