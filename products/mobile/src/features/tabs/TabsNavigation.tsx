import { useRouter } from 'expo-router'
import type { ReactElement } from 'react'
import type { ChatSheetEntry } from '@/features/chat/chatSheetEvents'
import { useInboxHasUnread } from '@/features/inbox/useInboxHasUnread'
import { useMobileProductFlags } from '@/lib/featureFlags'
import { BottomBar } from './BottomBar'
import { useNavPins } from './navPinStore'
import type { TabKey } from './tabHeaderStore'
import { tabRouteName } from './tabRoutes'
import { visibleNavPins } from './visibleNavPins'

export function TabsNavigation({ tab, onNavigate }: { tab: TabKey; onNavigate?: (tab: TabKey) => void }): ReactElement {
    const router = useRouter()
    const pins = useNavPins()
    const flags = useMobileProductFlags()
    const inboxUnread = useInboxHasUnread()
    const goTo = onNavigate ?? ((tab: TabKey): void => router.navigate(`/(tabs)/${tabRouteName(tab)}`))
    return (
        <BottomBar
            selected={tab === 'live' ? 'home' : tab}
            pins={visibleNavPins(pins, tab, flags)}
            inboxUnread={inboxUnread}
            onHome={() => goTo('live')}
            onInbox={() => goTo('inbox')}
            onChats={() => goTo('chats')}
            onViews={() => goTo('views')}
            onPin={goTo}
            onNewChat={() => router.push({ pathname: '/chat', params: { entry: 'compose' satisfies ChatSheetEntry } })}
        />
    )
}
