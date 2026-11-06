import { useRouter } from 'expo-router'
import type { ReactElement } from 'react'
import type { ChatSheetEntry } from '@/features/chat/chatSheetEvents'
import { useMobileProductFlags } from '@/lib/featureFlags'
import { BottomBar } from './BottomBar'
import { useNavPins } from './navPinStore'
import type { TabKey } from './tabHeaderStore'
import { visibleNavPins } from './visibleNavPins'

export function TabsNavigation({ tab, onNavigate }: { tab: TabKey; onNavigate?: (tab: TabKey) => void }): ReactElement {
    const router = useRouter()
    const pins = useNavPins()
    const flags = useMobileProductFlags()
    const goTo = onNavigate ?? ((tab: TabKey): void => router.navigate(`/(tabs)/${tab}`))
    return (
        <BottomBar
            selected={tab === 'inbox' ? 'home' : tab}
            pins={visibleNavPins(pins, tab, flags)}
            onHome={() => goTo('inbox')}
            onChats={() => goTo('chats')}
            onViews={() => goTo('views')}
            onPin={goTo}
            onNewChat={() => router.push({ pathname: '/chat', params: { entry: 'compose' satisfies ChatSheetEntry } })}
        />
    )
}
