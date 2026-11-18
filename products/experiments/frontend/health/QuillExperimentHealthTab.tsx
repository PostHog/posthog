import { useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { Card, Item, ItemContent, ItemDescription, ItemMedia, Spinner, Text } from '@posthog/quill'

import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { HealthChecksPanel } from './HealthChecksPanel'

export const HEALTH_LOAD_ERROR = "Couldn't load the health checks. Refresh the page to try again."

export function QuillExperimentHealthTab(): JSX.Element {
    const {
        experimentHealth,
        healthFindings,
        healthChecks,
        healthExposureChecks,
        isExperimentDraft,
        experimentHealthLoading,
        exposures,
    } = useValues(experimentLogic)

    if (healthFindings === null || healthChecks === null) {
        return experimentHealthLoading ? (
            <span className="flex items-center gap-2 py-8" data-attr="experiment-health-tab-loading">
                <Spinner />
                <Text size="xs" variant="muted" render={<span />}>
                    Running the health checks
                </Text>
            </span>
        ) : (
            <Item variant="outline" size="sm" tone="destructive">
                <ItemMedia variant="icon" aria-hidden>
                    <IconWarning />
                </ItemMedia>
                <ItemContent>
                    <ItemDescription className="line-clamp-none">{HEALTH_LOAD_ERROR}</ItemDescription>
                </ItemContent>
            </Item>
        )
    }

    return (
        <div className="flex flex-col gap-2" data-attr="experiment-health-tab">
            <Card size="sm" flush className="py-0">
                <HealthChecksPanel
                    checks={healthChecks}
                    findings={healthFindings}
                    // A server from before the setup was reported sends none, for example while a deploy rolls out.
                    setup={experimentHealth?.setup ?? null}
                    // A reset to draft keeps the previous exposure answer in the page, as for the checks.
                    exposures={isExperimentDraft ? null : (exposures ?? null)}
                    isDraft={isExperimentDraft}
                    exposureChecksMissing={healthExposureChecks === 'missing'}
                />
            </Card>
            {healthExposureChecks === 'pending' && (
                <span className="flex items-center gap-1">
                    <Spinner />
                    <Text size="xs" variant="muted" render={<span />}>
                        Checking the exposures
                    </Text>
                </span>
            )}
        </div>
    )
}
