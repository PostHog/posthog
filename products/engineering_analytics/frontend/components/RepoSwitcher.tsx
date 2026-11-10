import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonMenu } from 'lib/lemon-ui/LemonMenu/LemonMenu'

import { repoScopeLogic } from '../scenes/repoScopeLogic'

export function RepoSwitcher(): JSX.Element | null {
    const { hasMultipleSources, sourceOptions, selectedScope } = useValues(repoScopeLogic)
    const { switchRepo } = useActions(repoScopeLogic)

    if (!hasMultipleSources) {
        return null
    }
    return (
        <LemonMenu
            items={sourceOptions.map((option) => ({
                label: option.label,
                active: option.value === selectedScope,
                onClick: () => switchRepo(option.value),
            }))}
        >
            <LemonButton
                type="secondary"
                size="small"
                sideIcon={<IconChevronDown />}
                // Pinned to the data-attr of the repository picker this button replaced, because autocapture insights use it.
                data-attr="engineering-analytics-source-select"
            >
                Switch repository
            </LemonButton>
        </LemonMenu>
    )
}
