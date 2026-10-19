import type { ComponentType, ReactElement } from 'react'

import { track } from '@/lib/analytics'
import { HomeIcon } from '@/ui/icons/HomeIcon'
import { SpacesIcon } from '@/ui/icons/SpacesIcon'
import type { IconProps } from '@/ui/icons/types'
import { ViewsIcon } from '@/ui/icons/ViewsIcon'

import {
    DEFAULT_PAGES,
    type DefaultPage,
    defaultPageLabel,
    effectiveDefaultPage,
    useDefaultPageStore,
} from './defaultPageStore'
import { SettingsGroup } from './SettingsGroup'
import { SettingsRadioRow } from './SettingsRadioRow'

// The same glyphs as the bottom bar, so the rows read as the tabs they open.
const ICONS: Record<DefaultPage, ComponentType<IconProps>> = { inbox: HomeIcon, chats: SpacesIcon, views: ViewsIcon }

export function DefaultPageGroup(): ReactElement {
    const page = useDefaultPageStore((state) => effectiveDefaultPage(state.page))
    const setPage = useDefaultPageStore((state) => state.setPage)

    const choose = (next: DefaultPage): void => {
        if (next === page) {
            return
        }
        track('mobile_default_page_changed', { page: next, previous_page: page })
        setPage(next)
    }

    return (
        <SettingsGroup title="Start page" testID="settings-default-page">
            {DEFAULT_PAGES.map((option) => (
                <SettingsRadioRow
                    key={option}
                    label={defaultPageLabel(option)}
                    Icon={ICONS[option]}
                    selected={option === page}
                    onPress={() => choose(option)}
                    testID={`default-page-${option}`}
                />
            ))}
        </SettingsGroup>
    )
}
