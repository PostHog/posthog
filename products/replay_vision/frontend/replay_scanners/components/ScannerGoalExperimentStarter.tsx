import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconFlask } from '@posthog/icons'
import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import type { ExperimentBasicApi } from 'products/experiments/frontend/generated/api.schemas'

import { experimentScannerPickerLogic } from '../experimentScannerPickerLogic'

export interface ScannerGoalExperimentStarterProps {
    experiment: ExperimentBasicApi | null
    disabledReason: string | null
    onChange: (experiment: ExperimentBasicApi | null) => void
}

export function ScannerGoalExperimentStarter({
    experiment,
    disabledReason,
    onChange,
}: ScannerGoalExperimentStarterProps): JSX.Element | null {
    const { experimentOptions, experimentOptionsLoading, hasLoadedOptions, loadFailed, search } =
        useValues(experimentScannerPickerLogic)
    const { ensureOptionsLoaded, setSearch } = useActions(experimentScannerPickerLogic)
    // The picked experiment is kept as the object because a later search can drop it from the options.
    const options =
        experiment && !experimentOptions.some((option) => option.id === experiment.id)
            ? [experiment, ...experimentOptions]
            : experimentOptions

    useEffect(() => {
        ensureOptionsLoaded()
    }, [ensureOptionsLoaded])

    // Hidden until the first load answers, and when the project runs no experiment to pick. A failed load
    // still shows the starter so that opening the menu can retry. A picked experiment always shows, so that
    // the user can clear it.
    if (!experiment && !loadFailed && (!hasLoadedOptions || (!search && options.length === 0))) {
        return null
    }

    return (
        <LemonSelect<number>
            allowClear
            type="secondary"
            size="xsmall"
            icon={<IconFlask />}
            active={!!experiment}
            tooltip="The scanner watches the users in this experiment and describes how each variant plays out for them."
            disabledReason={disabledReason ?? undefined}
            loading={experimentOptionsLoading}
            value={experiment?.id ?? null}
            renderButtonContent={() => (experiment ? `Experiment: ${experiment.name}` : 'Track an experiment')}
            dropdownMatchSelectWidth={false}
            dropdownPlacement="bottom-start"
            menu={{
                className: 'min-w-80',
                onVisibilityChange: (visible) => visible && ensureOptionsLoaded(),
            }}
            options={[
                {
                    title: (
                        // The menu closes on any click inside it, which would dismiss it when the search box is clicked.
                        <div onClick={(e) => e.stopPropagation()}>
                            <LemonInput
                                type="search"
                                size="small"
                                fullWidth
                                autoFocus
                                placeholder="Search running experiments"
                                value={search}
                                onChange={setSearch}
                                data-attr="vision-goal-starter-experiment-search"
                            />
                        </div>
                    ),
                    // LemonSelect drops a section with no options, and the search box with it.
                    options:
                        options.length > 0
                            ? options.map((option) => ({ value: option.id, label: option.name }))
                            : [
                                  {
                                      value: 0,
                                      label: experimentOptionsLoading
                                          ? 'Searching...'
                                          : loadFailed
                                            ? "Couldn't load running experiments"
                                            : 'No running experiments match your search',
                                      disabledReason: loadFailed
                                          ? 'Close and reopen this menu to try again'
                                          : 'Try a different search',
                                  },
                              ],
                },
            ]}
            onChange={(id) => onChange(options.find((option) => option.id === id) ?? null)}
            data-attr="vision-goal-starter-experiment"
        />
    )
}
