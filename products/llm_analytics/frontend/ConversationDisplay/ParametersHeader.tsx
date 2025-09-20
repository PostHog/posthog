import { LemonTag } from '@posthog/lemon-ui'

import { EventType } from '~/types'

export function ParametersHeader({ eventProperties }: { eventProperties: EventType['properties'] }): JSX.Element {
    return (
        <div className="flex flex-row flex-wrap gap-2">
            {eventProperties.$ai_model_parameters &&
                Object.entries(eventProperties.$ai_model_parameters).map(
                    ([key, value]) =>
                        value !== null && (
                            <LemonTag key={key} type="muted">
                                {key}: {`${value}`}
                            </LemonTag>
                        )
                )}
        </div>
    )
}
