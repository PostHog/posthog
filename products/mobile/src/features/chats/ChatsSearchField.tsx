import type { ReactElement } from 'react'
import { StyleSheet, TextInput, View } from 'react-native'

import { CloseIcon } from '@/ui/icons/CloseIcon'
import { SearchIcon } from '@/ui/icons/SearchIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, iconSizes, inputReset, radii, type } from '@/ui/tokens'

interface ChatsSearchFieldProps {
    value: string
    onChangeText: (text: string) => void
}

export function ChatsSearchField({ value, onChangeText }: ChatsSearchFieldProps): ReactElement {
    return (
        <View style={styles.field}>
            <SearchIcon size={iconSizes.control} color={colors.tertiary} />
            <TextInput
                value={value}
                onChangeText={onChangeText}
                placeholder="Search chats"
                placeholderTextColor={colors.tertiary}
                style={styles.input}
                returnKeyType="search"
                autoCorrect={false}
                autoCapitalize="none"
                clearButtonMode="never"
                accessibilityLabel="Search chats"
                testID="chats-search"
            />
            {value ? (
                <Pressable44
                    onPress={() => onChangeText('')}
                    accessibilityLabel="Clear search"
                    pressedBackground={colors.sunken}
                    style={styles.clear}
                    testID="chats-search-clear"
                >
                    <CloseIcon size={iconSizes.inline} color={colors.secondary} />
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
        marginTop: 4,
        marginBottom: 4,
        paddingLeft: 14,
        paddingRight: 6,
        borderWidth: 1,
        borderColor: colors.hairline,
        borderRadius: radii.pill,
        backgroundColor: colors.white,
    },
    input: {
        ...inputReset,
        flex: 1,
        height: 42,
        paddingVertical: 0,
        ...type.input,
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
