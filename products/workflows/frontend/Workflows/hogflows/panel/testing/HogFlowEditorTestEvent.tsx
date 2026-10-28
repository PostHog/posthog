import { useActions, useValues } from 'kea'

import { IconRedo } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCollapse, Link, ProfilePicture, Spinner } from '@posthog/lemon-ui'

import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TZLabel } from 'lib/components/TZLabel'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { HogFunctionTestEditor } from 'scenes/hog-functions/configuration/HogFunctionTest'
import { FLAG_CALLS_NOT_LOADABLE } from 'scenes/hog-functions/filters/flagCallsMatching'
import { urls } from 'scenes/urls'

import { asDisplay } from 'products/persons/frontend/person-utils'

import { workflowLogic } from '../../../workflowLogic'
import { hogFlowEditorTestLogic } from './hogFlowEditorTestLogic'

export function HogFlowEditorTestEvent(): JSX.Element {
    const { logicProps } = useValues(workflowLogic)
    const {
        sampleGlobals,
        sampleGlobalsLoading,
        sampleGlobalsError,
        noMatchingEvents,
        canTryExtendedSearch,
        shouldLoadSampleGlobals,
        triggerMatchesOnlyFlagCallsOutsideEvents,
        eventPanelOpen,
        eventSelectorOpen,
        lastSearchedEventName,
    } = useValues(hogFlowEditorTestLogic(logicProps))
    const { loadSampleGlobals, loadSampleEventByName, setSampleGlobals, setEventPanelOpen, setEventSelectorOpen } =
        useActions(hogFlowEditorTestLogic(logicProps))

    const display = asDisplay(sampleGlobals?.person)
    const url = urls.personByDistinctId(sampleGlobals?.event?.distinct_id || '')

    return (
        <div className="flex-0">
            <LemonCollapse
                embedded
                multiple
                activeKeys={eventPanelOpen}
                onChange={setEventPanelOpen}
                panels={[
                    {
                        key: 'event',
                        header: sampleGlobalsLoading ? (
                            <>
                                Loading test event... <Spinner />
                            </>
                        ) : (
                            <>Test event: {sampleGlobals?.event?.event} </>
                        ),
                        className: 'bg-surface-secondary',
                        content: (
                            <div>
                                <div className="bg-surface-secondary">
                                    {sampleGlobalsError && (
                                        <div>
                                            <LemonBanner type="info" className="mb-2">
                                                {sampleGlobalsError}
                                            </LemonBanner>
                                            {canTryExtendedSearch && (
                                                <div className="mb-2 text-center">
                                                    <LemonButton
                                                        type="primary"
                                                        onClick={() => {
                                                            if (shouldLoadSampleGlobals) {
                                                                loadSampleGlobals({ extendedSearch: true })
                                                            } else {
                                                                // For non-event triggers, reload with the last searched event name
                                                                loadSampleEventByName({
                                                                    eventName: lastSearchedEventName || '$pageview',
                                                                    extendedSearch: true,
                                                                })
                                                            }
                                                        }}
                                                        loading={sampleGlobalsLoading}
                                                    >
                                                        Try searching last 30 days (slower)
                                                    </LemonButton>
                                                </div>
                                            )}
                                        </div>
                                    )}
                                    <div className="flex gap-2 items-center">
                                        <ProfilePicture name={display} />
                                        <div className="flex-1">
                                            {sampleGlobals?.person ? (
                                                <Link to={url} className="flex gap-2 items-center">
                                                    <span className="font-semibold">{display}</span>
                                                </Link>
                                            ) : sampleGlobals ? (
                                                <span className="text-muted">No associated person</span>
                                            ) : (
                                                <span className="text-muted">Loading...</span>
                                            )}{' '}
                                            <span className="text-muted">performed</span>{' '}
                                            <span className="space-y-1 font-semibold text-md">
                                                {sampleGlobals?.event?.event}
                                            </span>{' '}
                                            {sampleGlobals?.event?.timestamp && (
                                                <TZLabel time={sampleGlobals?.event?.timestamp} />
                                            )}
                                        </div>
                                        {shouldLoadSampleGlobals ? (
                                            <LemonButton
                                                type="secondary"
                                                onClick={() => loadSampleGlobals()}
                                                tooltip={
                                                    noMatchingEvents && !triggerMatchesOnlyFlagCallsOutsideEvents
                                                        ? 'No events match the current filters. Try adjusting your trigger filters.'
                                                        : 'Find the last event matching the trigger event filters, and use it to populate the globals for a test run.'
                                                }
                                                disabledReason={
                                                    noMatchingEvents
                                                        ? triggerMatchesOnlyFlagCallsOutsideEvents
                                                            ? FLAG_CALLS_NOT_LOADABLE
                                                            : 'No matching events found - adjust your trigger filters'
                                                        : undefined
                                                }
                                                icon={<IconRedo />}
                                                size="small"
                                            >
                                                Load new event
                                            </LemonButton>
                                        ) : (
                                            <Popover
                                                overlay={
                                                    <TaxonomicFilter
                                                        groupType={TaxonomicFilterGroupType.Events}
                                                        value={sampleGlobals?.event?.event || ''}
                                                        onChange={(_, value) => {
                                                            if (typeof value === 'string') {
                                                                loadSampleEventByName({ eventName: value })
                                                            }
                                                        }}
                                                        allowNonCapturedEvents
                                                        taxonomicGroupTypes={[
                                                            TaxonomicFilterGroupType.CustomEvents,
                                                            TaxonomicFilterGroupType.Events,
                                                        ]}
                                                    />
                                                }
                                                visible={eventSelectorOpen}
                                                onClickOutside={() => setEventSelectorOpen(false)}
                                                placement="bottom-end"
                                            >
                                                <LemonButton
                                                    type="secondary"
                                                    onClick={() => setEventSelectorOpen(!eventSelectorOpen)}
                                                    tooltip="Select an event type to load test data"
                                                    size="small"
                                                >
                                                    {sampleGlobals?.event?.event || 'Select event'}
                                                </LemonButton>
                                            </Popover>
                                        )}
                                    </div>

                                    {/* Event Properties */}
                                    {sampleGlobals && (
                                        <>
                                            <div className="text-sm mt-2">
                                                Here are all the global variables you can use in your workflow:
                                            </div>
                                            <div className="flex-col gap-2 my-3 max-h-48 overflow-auto">
                                                <HogFunctionTestEditor
                                                    value={JSON.stringify(sampleGlobals, null, 2)}
                                                    onChange={setSampleGlobals}
                                                />
                                            </div>
                                        </>
                                    )}
                                </div>
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}
