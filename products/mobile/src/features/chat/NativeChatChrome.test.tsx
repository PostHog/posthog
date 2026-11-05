import { Stack, useRouter } from 'expo-router'
import { fireEvent, renderRouter, screen } from 'expo-router/testing-library'
import { type ReactElement, useState } from 'react'
import { Button, TextInput, View } from 'react-native'

import { NativeChatChrome } from './NativeChatChrome'

function Chat(): ReactElement {
    const router = useRouter()
    const [text, setText] = useState('Keep this draft')
    const [revision, setRevision] = useState(0)
    return (
        <View>
            <NativeChatChrome
                onBack={() => router.back()}
                onNewChat={() => setText('')}
                onMore={() => undefined}
                hasActions
                disabledReason={revision % 2 ? 'Saving draft' : undefined}
            />
            <TextInput testID="draft" value={text} onChangeText={setText} />
            <Button title="Update session" onPress={() => setRevision((value) => value + 1)} />
        </View>
    )
}

function Layout(): ReactElement {
    return <Stack />
}

test('keeps the native chat and its draft mounted while session actions change', async () => {
    const app = await renderRouter({ _layout: Layout, chat: Chat }, { initialUrl: '/chat' })
    const input = screen.getByTestId('draft')
    for (let index = 0; index < 4; index++) fireEvent.press(screen.getByText('Update session'))
    expect(screen.getByTestId('draft')).toBe(input)
    expect(input.props.value).toBe('Keep this draft')
    expect(app.getPathname()).toBe('/chat')
})
