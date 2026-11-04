import { Stack } from 'expo-router'
import { Children, Fragment, isValidElement, type ReactElement, type ReactNode } from 'react'
import { nativeIcons } from './icons/nativeIcons'
import { useOverlayDismiss } from './overlayDismiss'
import type { ScreenChromeProps } from './ScreenChrome'
import { useColors } from './theme'

function toolbarItems(children: ReactNode): ReactNode[] {
    return Children.toArray(children).flatMap((child) =>
        isValidElement<{ children?: ReactNode }>(child) && child.type === Fragment
            ? toolbarItems(child.props.children)
            : [child]
    )
}

export function NativeScreenChrome({ onBack, nativeActions }: ScreenChromeProps): ReactElement {
    const colors = useColors()
    const dismiss = useOverlayDismiss()
    return (
        <>
            <Stack.Screen
                options={{
                    headerShown: true,
                    gestureEnabled: !dismiss,
                    headerTransparent: true,
                    headerStyle: { backgroundColor: colors.background },
                    headerLargeStyle: { backgroundColor: colors.background },
                    headerShadowVisible: false,
                    scrollEdgeEffects: { top: 'hidden' },
                    headerTitle: '',
                    headerTintColor: colors.ink,
                    headerBackVisible: false,
                }}
            />
            <Stack.Toolbar placement="left">
                <Stack.Toolbar.Button
                    iconRenderingMode="template"
                    icon={dismiss ? nativeIcons.close : nativeIcons.back}
                    accessibilityLabel={dismiss ? 'Close' : 'Back'}
                    onPress={dismiss ?? onBack}
                />
            </Stack.Toolbar>
            <Stack.Toolbar placement="right">{dismiss ? null : toolbarItems(nativeActions)}</Stack.Toolbar>
        </>
    )
}
