import { Stack } from 'expo-router'
import { Children, Fragment, isValidElement, type ReactElement, type ReactNode } from 'react'
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

export function NativeScreenChrome({ onBack, title, nativeActions, hideNativeTitle }: ScreenChromeProps): ReactElement {
    const colors = useColors()
    const dismiss = useOverlayDismiss()
    return (
        <>
            <Stack.Screen
                options={{
                    headerShown: true,
                    gestureEnabled: !dismiss,
                    headerTransparent: true,
                    headerTitle: dismiss || hideNativeTitle ? '' : (title?.text ?? ''),
                    headerTintColor: colors.ink,
                    headerBackVisible: false,
                }}
            />
            <Stack.Toolbar placement="left">
                <Stack.Toolbar.Button
                    icon={dismiss ? 'xmark' : 'chevron.backward'}
                    accessibilityLabel={dismiss ? 'Close' : 'Back'}
                    onPress={dismiss ?? onBack}
                />
            </Stack.Toolbar>
            <Stack.Toolbar placement="right">{dismiss ? null : toolbarItems(nativeActions)}</Stack.Toolbar>
        </>
    )
}
