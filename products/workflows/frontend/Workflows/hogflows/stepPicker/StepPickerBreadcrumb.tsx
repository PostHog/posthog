import { useActions, useValues } from 'kea'

import { IconChevronRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { stepPickerLogic } from './stepPickerLogic'
import { STEP_PICKER_VIEW_LABELS } from './stepPickerPresentation'

type Crumb = { label: string; onClick?: () => void }

export function StepPickerBreadcrumb(): JSX.Element {
    const { view, isSearching, openedProvider } = useValues(stepPickerLogic)
    const { setView, closeProvider } = useActions(stepPickerLogic)
    const viewLabel = STEP_PICKER_VIEW_LABELS[view]

    const crumbs: Crumb[] = isSearching
        ? [{ label: STEP_PICKER_VIEW_LABELS.all, onClick: () => setView('all') }, { label: 'Search' }]
        : openedProvider
          ? [{ label: viewLabel, onClick: closeProvider }, { label: openedProvider.label }]
          : [{ label: viewLabel }]

    return (
        <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1 border-b px-3 py-2 text-xs">
            {crumbs.map((crumb, index) => (
                <span key={index} className="flex min-w-0 items-center gap-1">
                    {index > 0 ? <IconChevronRight className="shrink-0 text-secondary" /> : null}
                    {crumb.onClick ? (
                        <LemonButton size="xsmall" onClick={crumb.onClick}>
                            {crumb.label}
                        </LemonButton>
                    ) : (
                        <span className="truncate px-1 font-semibold">{crumb.label}</span>
                    )}
                </span>
            ))}
        </nav>
    )
}
