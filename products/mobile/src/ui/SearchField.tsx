import { type ReactElement, useState } from 'react'
import { TextInput, View } from 'react-native'

import { CloseIcon } from '@/ui/icons/CloseIcon'
import { SearchIcon } from '@/ui/icons/SearchIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useTheme } from '@/ui/theme'
import { inputReset, radii } from '@/ui/tokens'

interface SearchFieldProps {
    value: string
    onChangeText: (text: string) => void
    placeholder: string
    testID: string
}

export function SearchField({ value, onChangeText, placeholder, testID }: SearchFieldProps): ReactElement {
    const { colors, scheme } = useTheme()
    const styles = useStyles()
    const [focused, setFocused] = useState(false)
    return (
        <View style={[styles.ring, focused && styles.ringFocused]}>
            <View style={[styles.field, focused && styles.fieldFocused]}>
                <SearchIcon size={18} color={colors.tertiary} />
                <TextInput
                    value={value}
                    onChangeText={onChangeText}
                    onFocus={() => setFocused(true)}
                    onBlur={() => setFocused(false)}
                    placeholder={placeholder}
                    placeholderTextColor={colors.tertiary}
                    keyboardAppearance={scheme}
                    style={styles.input}
                    returnKeyType="search"
                    autoCorrect={false}
                    autoCapitalize="none"
                    clearButtonMode="never"
                    accessibilityLabel={placeholder}
                    testID={testID}
                />
                {value ? (
                    <Pressable44
                        onPress={() => onChangeText('')}
                        accessibilityLabel="Clear search"
                        pressedBackground={colors.sunken}
                        style={styles.clear}
                        testID={`${testID}-clear`}
                    >
                        <CloseIcon size={12} color={colors.secondary} />
                    </Pressable44>
                ) : null}
            </View>
        </View>
    )
}

const RING = 3

const useStyles = createStyles(({ colors }) => ({
    // The focus ring draws outside the field, so focusing it moves nothing.
    ring: {
        margin: -RING,
        padding: RING,
        borderRadius: radii.card + RING,
    },
    ringFocused: {
        backgroundColor: colors.blueHighlight,
    },
    fieldFocused: {
        borderColor: colors.border,
    },
    field: {
        height: 44,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        paddingLeft: 14,
        paddingRight: 6,
        borderWidth: 1,
        borderColor: colors.hairline,
        borderRadius: radii.card,
        backgroundColor: colors.surface,
    },
    input: {
        ...inputReset,
        flex: 1,
        height: 42,
        paddingVertical: 0,
        fontSize: 16,
        lineHeight: 20,
        textAlignVertical: 'center',
        includeFontPadding: false,
        color: colors.ink,
    },
    // Visual 32pt; the default hit slop brings the target to 44pt.
    clear: {
        width: 32,
        height: 32,
        borderRadius: radii.pill,
        alignItems: 'center',
        justifyContent: 'center',
    },
}))
