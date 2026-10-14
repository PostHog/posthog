import type { ReactElement } from 'react'
import { StyleSheet, TextInput, View } from 'react-native'

import { CloseIcon } from '@/ui/icons/CloseIcon'
import { SearchIcon } from '@/ui/icons/SearchIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, inputReset, radii } from '@/ui/tokens'

interface ViewsSearchFieldProps {
    value: string
    onChangeText: (text: string) => void
    placeholder: string
    testID: string
}

export function ViewsSearchField({ value, onChangeText, placeholder, testID }: ViewsSearchFieldProps): ReactElement {
    return (
        <View style={styles.field}>
            <SearchIcon size={18} color={colors.tertiary} />
            <TextInput
                value={value}
                onChangeText={onChangeText}
                placeholder={placeholder}
                placeholderTextColor={colors.tertiary}
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
    )
}

const styles = StyleSheet.create({
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
        backgroundColor: colors.white,
    },
    input: {
        ...inputReset,
        flex: 1,
        height: 42,
        paddingVertical: 0,
        fontSize: 16,
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
})
