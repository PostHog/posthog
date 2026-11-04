import { Stack } from 'expo-router'
import { type ReactElement, useCallback, useMemo, useRef } from 'react'
import { nativeIcons } from '@/ui/icons/nativeIcons'
import { useOverlayDismiss } from '@/ui/overlayDismiss'
import { useColors } from '@/ui/theme'

export function NativeChatChrome({
    onBack,
    onNewChat,
    onMore,
    hasActions,
    disabledReason,
}: {
    onBack: () => void
    onNewChat: () => void
    onMore: () => void
    hasActions: boolean
    disabledReason?: string
}): ReactElement {
    const colors = useColors()
    const dismiss = useOverlayDismiss()
    const latest = useRef({ onBack, onNewChat, onMore, dismiss })
    latest.current = { onBack, onNewChat, onMore, dismiss }
    const back = useCallback(() => (latest.current.dismiss ?? latest.current.onBack)(), [])
    const compose = useCallback(() => latest.current.onNewChat(), [])
    const more = useCallback(() => latest.current.onMore(), [])
    const options = useMemo(
        () => ({
            headerShown: true,
            headerTransparent: true,
            headerStyle: { backgroundColor: colors.background },
            headerLargeStyle: { backgroundColor: colors.background },
            headerShadowVisible: false,
            scrollEdgeEffects: { top: 'hidden' as const },
            headerTitle: '',
            headerTintColor: colors.ink,
            headerBackVisible: false,
            gestureEnabled: !dismiss,
        }),
        [colors.ink, colors.background, dismiss]
    )
    const leading = useMemo(
        () => (
            <Stack.Toolbar.Button
                iconRenderingMode="template"
                icon={dismiss ? nativeIcons.close : nativeIcons.back}
                accessibilityLabel={dismiss ? 'Close' : 'Back'}
                onPress={back}
            />
        ),
        [back, dismiss]
    )
    const trailing = useMemo(
        () =>
            !dismiss && hasActions
                ? [
                      <Stack.Toolbar.Button
                          iconRenderingMode="template"
                          key="new"
                          icon={nativeIcons.compose}
                          accessibilityLabel="New chat"
                          disabled={!!disabledReason}
                          accessibilityHint={disabledReason}
                          onPress={compose}
                      />,
                      <Stack.Toolbar.Button
                          iconRenderingMode="template"
                          key="more"
                          icon={nativeIcons.more}
                          accessibilityLabel="Chat options"
                          onPress={more}
                      />,
                  ]
                : null,
        [hasActions, disabledReason, compose, more, dismiss]
    )
    return (
        <>
            <Stack.Screen options={options} />
            <Stack.Toolbar placement="left">{leading}</Stack.Toolbar>
            <Stack.Toolbar placement="right">{trailing}</Stack.Toolbar>
        </>
    )
}
