import type { ReactElement } from 'react'

import { track } from '@/lib/analytics'

import {
    DEFAULT_PAGES,
    type DefaultPage,
    defaultPageLabel,
    effectiveDefaultPage,
    useDefaultPageStore,
} from './defaultPageStore'
import { SettingsGroup } from './SettingsGroup'
import { SettingsRadioRow } from './SettingsRadioRow'

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
                    selected={option === page}
                    onPress={() => choose(option)}
                    testID={`default-page-${option}`}
                />
            ))}
        </SettingsGroup>
    )
}
