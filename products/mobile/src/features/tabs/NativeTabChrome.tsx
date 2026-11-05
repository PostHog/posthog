import { Stack, useRouter } from 'expo-router'
import { type ReactElement, useCallback, useMemo, useRef } from 'react'
import type { ChatSheetEntry } from '@/features/chat/chatSheetEvents'
import { nativeIcons } from '@/ui/icons/nativeIcons'
import { useOverlayDismiss } from '@/ui/overlayDismiss'
import { useColors } from '@/ui/theme'
import { useNativeHeaderCleanup } from '@/ui/useNativeHeaderCleanup'
import type { TabHeaderSlot } from './tabHeaderStore'

export function NativeTabChrome({ slot, onMore }: { slot: TabHeaderSlot | null; onMore: () => void }): ReactElement {
    useNativeHeaderCleanup()
    const colors = useColors()
    const router = useRouter()
    const dismiss = useOverlayDismiss()
    const latest = useRef({ slot, onMore, dismiss })
    latest.current = { slot, onMore, dismiss }
    const close = useCallback(() => latest.current.dismiss?.(), [])
    const filter = useCallback(() => latest.current.slot?.filter?.onPress(), [])
    const more = useCallback(() => latest.current.onMore(), [])
    const done = useCallback(() => latest.current.slot?.editing?.onDone(), [])
    const compose = useCallback(
        () => router.push({ pathname: '/chat', params: { entry: 'compose' satisfies ChatSheetEntry } }),
        [router]
    )
    const options = useMemo(
        () => ({
            headerShown: true,
            headerTransparent: true,
            headerTitle: '',
            headerBackVisible: false,
            headerShadowVisible: false,
            headerStyle: { backgroundColor: colors.background },
            headerTintColor: colors.ink,
            gestureEnabled: !dismiss,
            scrollEdgeEffects: { top: 'hidden' as const },
        }),
        [colors.background, colors.ink, dismiss]
    )
    const editing = !!slot?.editing
    const hasFilter = !!slot?.filter
    const activeFilter = slot?.filter?.active ?? false
    const leading = useMemo(
        () =>
            dismiss ? (
                <Stack.Toolbar.Button
                    iconRenderingMode="template"
                    icon={nativeIcons.close}
                    accessibilityLabel="Close"
                    onPress={close}
                />
            ) : null,
        [dismiss, close]
    )
    const trailing = useMemo(
        () =>
            dismiss
                ? null
                : editing
                  ? [
                        <Stack.Toolbar.Button
                            iconRenderingMode="template"
                            key="done"
                            icon={nativeIcons.done}
                            accessibilityLabel="Done"
                            onPress={done}
                        />,
                    ]
                  : [
                        ...(hasFilter
                            ? [
                                  <Stack.Toolbar.Button
                                      iconRenderingMode="template"
                                      key="filter"
                                      icon={nativeIcons.filter}
                                      accessibilityLabel="Filter and sort"
                                      selected={activeFilter}
                                      onPress={filter}
                                  />,
                              ]
                            : []),
                        <Stack.Toolbar.Button
                            iconRenderingMode="template"
                            key="compose"
                            icon={nativeIcons.compose}
                            accessibilityLabel="Chat"
                            variant="prominent"
                            separateBackground
                            onPress={compose}
                        />,
                        <Stack.Toolbar.Button
                            iconRenderingMode="template"
                            key="more"
                            icon={nativeIcons.more}
                            accessibilityLabel="More"
                            onPress={more}
                        />,
                    ],
        [dismiss, editing, hasFilter, activeFilter, done, filter, compose, more]
    )
    return (
        <>
            <Stack.Screen options={options} />
            <Stack.Toolbar placement="left">{leading}</Stack.Toolbar>
            <Stack.Toolbar placement="right">{trailing}</Stack.Toolbar>
        </>
    )
}
