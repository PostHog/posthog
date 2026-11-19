import type { ReactElement } from 'react'
import { Platform, StyleSheet, Switch } from 'react-native'

import { track } from '@/lib/analytics'
import { useColors } from '@/ui/theme'

import { useInternalUsersFilter, useInternalUsersPreference } from './internalUsersPreference'
import { SettingsRow } from './SettingsRow'

const LABEL = 'Exclude internal users'

export function InternalUsersToggle({ description, testID }: { description?: string; testID: string }): ReactElement {
    const colors = useColors()
    const exclude = useInternalUsersFilter()
    const setExclude = useInternalUsersPreference((state) => state.setExclude)
    const webSwitchProps = Platform.OS === 'web' ? { activeThumbColor: colors.white } : {}

    const change = (enabled: boolean): void => {
        if (exclude === undefined || enabled === exclude) return
        setExclude(enabled)
        track('mobile_internal_users_filter_changed', { enabled })
    }

    return (
        <SettingsRow
            label={LABEL}
            description={description}
            style={description ? styles.descriptionRow : undefined}
            accessory={
                <Switch
                    {...webSwitchProps}
                    value={exclude ?? false}
                    onValueChange={change}
                    disabled={exclude === undefined}
                    trackColor={{ true: colors.switchOn, false: colors.switchOff }}
                    thumbColor={colors.white}
                    accessibilityLabel={LABEL}
                    testID={testID}
                />
            }
        />
    )
}

const styles = StyleSheet.create({
    descriptionRow: { paddingVertical: 16 },
})
