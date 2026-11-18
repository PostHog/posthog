import type { ReactElement } from 'react'
import { Platform, Switch } from 'react-native'

import { useColors } from '@/ui/theme'

import { useInternalUsersFilter, useInternalUsersPreference } from './internalUsersPreference'
import { SettingsRow } from './SettingsRow'

const LABEL = 'Exclude internal users'

export function InternalUsersToggle({ testID }: { testID: string }): ReactElement {
    const colors = useColors()
    const exclude = useInternalUsersFilter()
    const setExclude = useInternalUsersPreference((state) => state.setExclude)
    const webSwitchProps = Platform.OS === 'web' ? { activeThumbColor: colors.white } : {}
    return (
        <SettingsRow
            label={LABEL}
            accessory={
                <Switch
                    {...webSwitchProps}
                    value={exclude ?? false}
                    onValueChange={setExclude}
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
