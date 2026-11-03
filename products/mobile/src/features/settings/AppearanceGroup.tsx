import type { ComponentType, ReactElement } from 'react'

import { track } from '@/lib/analytics'
import { APPEARANCES, type Appearance, useAppearanceStore } from '@/ui/appearanceStore'
import { MoonIcon } from '@/ui/icons/MoonIcon'
import { PhoneIcon } from '@/ui/icons/PhoneIcon'
import { SunIcon } from '@/ui/icons/SunIcon'
import type { IconProps } from '@/ui/icons/types'
import { SettingsGroup } from './SettingsGroup'
import { SettingsRadioRow } from './SettingsRadioRow'

const LABELS: Record<Appearance, string> = { system: 'Match system', light: 'Light', dark: 'Dark' }

const ICONS: Record<Appearance, ComponentType<IconProps>> = { system: PhoneIcon, light: SunIcon, dark: MoonIcon }

export function AppearanceGroup(): ReactElement {
    const appearance = useAppearanceStore((state) => state.appearance)
    const setAppearance = useAppearanceStore((state) => state.setAppearance)

    const choose = (next: Appearance): void => {
        if (next === appearance) {
            return
        }
        track('mobile_appearance_changed', { appearance: next, previous_appearance: appearance })
        setAppearance(next)
    }

    return (
        <SettingsGroup title="Appearance" testID="settings-appearance">
            {APPEARANCES.map((option) => (
                <SettingsRadioRow
                    key={option}
                    label={LABELS[option]}
                    Icon={ICONS[option]}
                    selected={option === appearance}
                    onPress={() => choose(option)}
                    testID={`appearance-${option}`}
                />
            ))}
        </SettingsGroup>
    )
}
