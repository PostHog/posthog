import { type ReactElement, useState } from 'react'
import { Text, TextInput, View } from 'react-native'
import { useReanimatedKeyboardAnimation } from 'react-native-keyboard-controller'
import Animated, { useAnimatedStyle } from 'react-native-reanimated'

import { GitBranchIcon } from '@/ui/icons/GitBranchIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useTheme } from '@/ui/theme'
import { iconSizes, inputReset, radii, type } from '@/ui/tokens'

import { SheetPageHeader } from './SheetPageHeader'

interface BranchPageProps {
    branch: string
    onChange: (branch: string) => void
    onDone: (openedWith: string) => void
}

export function BranchPage({ branch, onChange, onDone }: BranchPageProps): ReactElement {
    const { colors, scheme } = useTheme()
    const styles = useStyles()
    const [openedWith] = useState(branch)
    const [draft, setDraft] = useState(branch)
    const keyboard = useReanimatedKeyboardAnimation()
    // The sheet sits on the bottom edge, so it grows by the keyboard's height to keep the field in view.
    const keyboardStyle = useAnimatedStyle(() => ({ paddingBottom: Math.max(-keyboard.height.value, 0) }))
    const change = (text: string): void => {
        setDraft(text)
        onChange(text)
    }
    const done = (): void => onDone(openedWith)

    return (
        <Animated.View style={keyboardStyle} testID="handoff-branch-page">
            <SheetPageHeader title="Branch" onBack={done} testID="handoff-branch-page" />
            <View style={styles.field}>
                <GitBranchIcon size={iconSizes.control} color={colors.tertiary} />
                <TextInput
                    value={draft}
                    onChangeText={change}
                    onSubmitEditing={done}
                    placeholder="Branch name"
                    placeholderTextColor={colors.tertiary}
                    keyboardAppearance={scheme}
                    autoFocus
                    autoCorrect={false}
                    autoCapitalize="none"
                    returnKeyType="done"
                    style={styles.input}
                    accessibilityLabel="Branch"
                    testID="handoff-branch-input"
                />
            </View>
            <Text style={styles.note}>
                PostHog picks the repository from the report. Leave this empty to use the base branch set for that
                repository in Inbox settings, or its default branch if none is set.
            </Text>
            <Pressable44
                onPress={done}
                pressedBackground={colors.inkHover}
                style={styles.button}
                testID="handoff-branch-done"
            >
                <Text style={styles.buttonText}>Done</Text>
            </Pressable44>
        </Animated.View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    field: {
        marginTop: 8,
        height: 48,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
        paddingHorizontal: 14,
    },
    input: {
        ...inputReset,
        ...type.body,
        flex: 1,
        minWidth: 0,
        color: colors.ink,
        paddingVertical: 0,
    },
    note: {
        ...type.meta,
        color: colors.muted,
        marginTop: 10,
        paddingHorizontal: 4,
    },
    button: {
        marginTop: 16,
        height: 48,
        borderRadius: radii.card,
        backgroundColor: colors.ink,
        alignItems: 'center',
        justifyContent: 'center',
    },
    buttonText: {
        ...type.buttonSmall,
        color: colors.onInk,
    },
}))
