import { useActions, useValues } from 'kea'

import {
    IconAI,
    IconClockRewind,
    IconDecisionTree,
    IconList,
    IconLogomark,
    IconSparkles,
    IconStar,
} from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { stepPickerLogic } from './stepPickerLogic'
import { STEP_PICKER_VIEW_LABELS, StepPickerView } from './stepPickerPresentation'

const VIEW_ICONS: Record<StepPickerView, JSX.Element> = {
    all: <IconList />,
    highlights: <IconSparkles />,
    ai: <IconAI />,
    favorites: <IconStar />,
    recents: <IconClockRewind />,
    posthog: <IconLogomark />,
    flow: <IconDecisionTree />,
}

const VIEWS_AFTER_DIVIDER: StepPickerView[] = ['posthog', 'flow']

export function StepPickerRail(): JSX.Element {
    const { view, visibleViews, isSearching } = useValues(stepPickerLogic)
    const { setView } = useActions(stepPickerLogic)

    const railButton = (railView: StepPickerView): JSX.Element => (
        <li key={railView}>
            <LemonButton
                size="small"
                fullWidth
                active={view === railView && !isSearching}
                icon={VIEW_ICONS[railView]}
                tooltip={STEP_PICKER_VIEW_LABELS[railView]}
                tooltipPlacement="right"
                onClick={() => setView(railView)}
                data-attr={`workflow-step-picker-view-${railView}`}
            >
                <span className="@max-[56rem]/step-picker:hidden">{STEP_PICKER_VIEW_LABELS[railView]}</span>
            </LemonButton>
        </li>
    )

    return (
        <nav
            aria-label="Views"
            className="flex w-44 shrink-0 flex-col gap-2 overflow-y-auto border-r p-2 @max-[56rem]/step-picker:w-12"
        >
            <ul className="flex flex-col gap-0.5">
                {visibleViews.filter((railView) => !VIEWS_AFTER_DIVIDER.includes(railView)).map(railButton)}
            </ul>
            <ul className="flex flex-col gap-0.5 border-t pt-2">
                {visibleViews.filter((railView) => VIEWS_AFTER_DIVIDER.includes(railView)).map(railButton)}
            </ul>
        </nav>
    )
}
