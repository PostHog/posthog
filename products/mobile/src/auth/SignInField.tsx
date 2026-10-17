import type { ReactElement } from 'react'
import { StyleSheet, Text, TextInput, type TextInputProps, View } from 'react-native'

import { colors, inputReset, radii, type } from '@/ui/tokens'

interface SignInFieldProps extends Pick<TextInputProps, 'value' | 'onChangeText' | 'placeholder' | 'keyboardType'> {
    label: string
    secret?: boolean
    hint?: string
    editable?: boolean
    testID?: string
}

export function SignInField({
    label,
    secret = false,
    hint,
    editable = true,
    testID,
    ...input
}: SignInFieldProps): ReactElement {
    return (
        <View style={styles.field}>
            <Text style={[type.eyebrow, styles.label]}>{label.toUpperCase()}</Text>
            <TextInput
                {...input}
                editable={editable}
                secureTextEntry={secret}
                placeholderTextColor={colors.tertiary}
                autoCapitalize="none"
                autoCorrect={false}
                spellCheck={false}
                style={[styles.input, !editable && styles.disabled]}
                accessibilityLabel={label}
                testID={testID}
            />
            {hint ? <Text style={styles.hint}>{hint}</Text> : null}
        </View>
    )
}

const styles = StyleSheet.create({
    field: {
        gap: 8,
    },
    label: {
        color: colors.tertiary,
        paddingHorizontal: 4,
    },
    input: {
        ...inputReset,
        height: 48,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.white,
        paddingHorizontal: 18,
        ...type.input,
        color: colors.ink,
    },
    disabled: {
        color: colors.tertiary,
    },
    hint: {
        ...type.metaSmall,
        color: colors.secondary,
        paddingHorizontal: 4,
    },
})
