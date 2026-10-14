import { BindLogic, useActions, useValues } from 'kea'

import { IconSearch } from '@posthog/icons'
import { LemonInput } from '@posthog/lemon-ui'

import { StepPickerList } from './StepPickerList'
import { StepPickerLogicProps, stepPickerLogic } from './stepPickerLogic'
import { StepPickerProviderDetail } from './StepPickerProviderDetail'
import { StepPickerRail } from './StepPickerRail'
import { StepPickerStepDetail } from './StepPickerStepDetail'

export function StepPicker(props: StepPickerLogicProps): JSX.Element {
    const logic = stepPickerLogic(props)
    const { search, selectedStep, openedProvider } = useValues(logic)
    const { setSearch } = useActions(logic)

    return (
        <BindLogic logic={stepPickerLogic} props={props}>
            <div
                className="@container/step-picker flex h-full min-h-0 min-w-0 flex-col"
                data-attr="workflow-step-picker"
            >
                <div className="border-b p-2">
                    <LemonInput
                        type="search"
                        size="large"
                        prefix={<IconSearch />}
                        placeholder="Search steps"
                        value={search}
                        onChange={setSearch}
                        autoFocus
                        fullWidth
                        data-attr="workflow-step-picker-search"
                    />
                </div>
                <div className="flex min-h-0 flex-1">
                    <StepPickerRail />
                    <StepPickerList />
                    <section
                        aria-label="Step details"
                        className="min-w-0 flex-1 overflow-y-auto @max-[44rem]/step-picker:hidden"
                    >
                        {selectedStep ? (
                            <StepPickerStepDetail entry={selectedStep} />
                        ) : openedProvider ? (
                            <StepPickerProviderDetail provider={openedProvider} />
                        ) : (
                            <div className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center text-sm text-secondary">
                                <IconSearch className="text-2xl" />
                                <span>
                                    Pick a step to see what it does, or open a product or vendor to see its steps.
                                </span>
                            </div>
                        )}
                    </section>
                </div>
            </div>
        </BindLogic>
    )
}
