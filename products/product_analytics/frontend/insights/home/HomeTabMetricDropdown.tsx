import { IconChevronDown } from '@posthog/icons'
import { LemonMenu } from '@posthog/lemon-ui'

import type { HomeTabMetricKey } from './homeTabDefaultLogic'

interface HomeTabMetricDropdownProps {
    value: HomeTabMetricKey
    options: { key: HomeTabMetricKey; title: string }[]
    onChange: (key: HomeTabMetricKey) => void
}

/** Chart title that switches the metric, matching the graph tile on the web analytics dashboard. */
export function HomeTabMetricDropdown({ value, options, onChange }: HomeTabMetricDropdownProps): JSX.Element {
    const currentTitle = options.find((option) => option.key === value)?.title ?? value

    return (
        <LemonMenu
            items={options.map((option) => ({
                label: option.title,
                active: option.key === value,
                onClick: () => onChange(option.key),
            }))}
            placement="bottom-start"
        >
            <button
                type="button"
                className="m-0 inline-flex min-w-0 max-w-full cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-base font-semibold text-current underline decoration-dotted decoration-from-font underline-offset-4 hover:text-accent"
                data-attr="home-tab-chart-metric-dropdown"
            >
                <span className="truncate">{currentTitle}</span>
                <IconChevronDown className="shrink-0 text-lg" />
            </button>
        </LemonMenu>
    )
}
