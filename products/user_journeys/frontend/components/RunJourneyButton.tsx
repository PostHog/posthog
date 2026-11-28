import { useActions, useValues } from 'kea'

import { IconPlay } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDropdown, LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { userJourneyRunsLogic } from '../userJourneyRunsLogic'

export interface RunJourneyButtonProps {
    journeyId: string
    /** Origin of the page a run opens when no other origin is given. */
    defaultOrigin: string | null
    /** Why the journey can't run, or null when it can. */
    disabledReason: string | null
}

export function RunJourneyButton({ journeyId, defaultOrigin, disabledReason }: RunJourneyButtonProps): JSX.Element {
    const logic = userJourneyRunsLogic({ journeyId })
    const { runFormOpen, baseUrl, baseUrlError, startingRun, startRunError, activeRun } = useValues(logic)
    const { setRunFormOpen, setBaseUrl, startRun } = useActions(logic)

    return (
        <LemonDropdown
            visible={runFormOpen}
            onVisibilityChange={setRunFormOpen}
            closeOnClickInside={false}
            placement="bottom-end"
            overlay={
                <form
                    className="flex flex-col gap-3 p-2 w-100 max-w-full"
                    onSubmit={(event) => {
                        event.preventDefault()
                        startRun()
                    }}
                >
                    <LemonField.Pure
                        label="Run against"
                        showOptional
                        error={baseUrlError}
                        help={
                            defaultOrigin
                                ? `Leave empty to run against ${defaultOrigin}. Enter another origin, such as a preview deploy, to open the same pages there.`
                                : 'Enter another origin, such as a preview deploy, to open the same pages there.'
                        }
                    >
                        <LemonInput
                            value={baseUrl}
                            onChange={setBaseUrl}
                            placeholder={defaultOrigin ?? 'https://preview.example.com'}
                            autoFocus
                            data-attr="user-journey-run-base-url"
                        />
                    </LemonField.Pure>
                    {startRunError ? <LemonBanner type="error">{startRunError}</LemonBanner> : null}
                    <LemonButton
                        type="primary"
                        htmlType="submit"
                        center
                        fullWidth
                        loading={startingRun}
                        disabledReason={baseUrlError ? 'Fix the URL first' : undefined}
                        data-attr="user-journey-run-start"
                    >
                        Start run
                    </LemonButton>
                </form>
            }
        >
            <LemonButton
                type="primary"
                size="small"
                icon={<IconPlay />}
                disabledReason={
                    disabledReason ?? (activeRun ? 'A run is in progress. Wait for it to finish.' : undefined)
                }
                data-attr="user-journey-run-now"
            >
                Run now
            </LemonButton>
        </LemonDropdown>
    )
}
