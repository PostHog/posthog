import { Stack } from 'expo-router'
import type { ReactElement } from 'react'

import { trackLiveAudienceChanged } from './analytics'
import { useLivePreference } from './livePreference'

const OPTIONS = [
    { key: 'all', label: 'All' },
    { key: 'web', label: 'Web' },
    { key: 'mobile', label: 'Mobile' },
] as const

export function useLiveAudienceNativeMenu(enabled = true): ReactElement | null {
    const { preference, setPreference } = useLivePreference()
    const selected = OPTIONS.find((option) => option.key === preference)?.label ?? 'All'
    if (!enabled) return null
    return (
        <Stack.Toolbar.Menu key="live-audience" accessibilityLabel={`Live view: ${selected}. Change view`}>
            {preference === 'all' ? <Stack.Toolbar.Icon sf="globe" /> : null}
            <Stack.Toolbar.Label>{selected}</Stack.Toolbar.Label>
            {OPTIONS.map((option) => (
                <Stack.Toolbar.MenuAction
                    key={option.key}
                    isOn={preference === option.key}
                    onPress={() => {
                        if (preference !== option.key) {
                            trackLiveAudienceChanged({ preference: option.key })
                            setPreference(option.key)
                        }
                    }}
                >
                    {option.key === 'all' ? <Stack.Toolbar.Icon sf="globe" /> : null}
                    <Stack.Toolbar.Label>{option.label}</Stack.Toolbar.Label>
                </Stack.Toolbar.MenuAction>
            ))}
        </Stack.Toolbar.Menu>
    )
}
