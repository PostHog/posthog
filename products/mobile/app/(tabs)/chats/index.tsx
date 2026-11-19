import type { ReactElement } from 'react'
import { ChatsScreen } from '@/features/chats/ChatsScreen'
import { TabScene } from '@/features/tabs/TabScene'

export default function ChatsRoute(): ReactElement {
    return (
        <TabScene tab="chats">
            <ChatsScreen />
        </TabScene>
    )
}
