import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner, LemonButton, LemonLabel } from '@posthog/lemon-ui'

import IngestionControls from 'lib/components/IngestionControls'
import { IngestionControlsSummary } from 'lib/components/IngestionControls/Summary'
import { UrlConfigLogicProps, urlConfigLogic } from 'lib/components/IngestionControls/triggers/urlConfigLogic'
import { ErrorTrackingAutoCaptureControls } from 'lib/components/IngestionControls/types'

import { AccessControlResourceType } from '~/types'

import { autoCaptureControlsLogic } from './autoCaptureControlsLogic'

export function ErrorTrackingIngestionControls({ disabled }: { disabled: boolean }): JSX.Element | null {
    const logic = autoCaptureControlsLogic

    const {
        controls,
        controlsLoading,
        hasControls,
        triggers,
        matchType,
        sampleRate,
        linkedFeatureFlag,
        eventTriggers,
        urlTriggers,
    } = useValues(logic)
    const {
        loadControls,
        createControls,
        setMatchType,
        setSampleRate,
        setLinkedFeatureFlag,
        setEventTriggers,
        setUrlTriggers,
    } = useActions(logic)

    useEffect(() => {
        loadControls()
        // oxlint-disable-next-line exhaustive-deps
    }, [])

    if (controlsLoading && controls === null) {
        return null
    }

    if (!hasControls) {
        return (
            <LemonButton type="primary" onClick={() => createControls()}>
                Enable autocapture controls
            </LemonButton>
        )
    }

    return (
        <IngestionControls
            logicKey="error-tracking"
            resourceType={AccessControlResourceType.ErrorTracking}
            matchType={matchType}
            onChangeMatchType={setMatchType}
        >
            <div className="space-y-2">
                {disabled && (
                    <LemonBanner type="warning">
                        <strong>Exception autocapture is disabled.</strong> Ingestion controls will only apply when it
                        is enabled.
                    </LemonBanner>
                )}
                <div className="flex flex-col gap-y-2">
                    <IngestionControlsSummary triggers={triggers} controlDescription="exceptions captured" />
                    <div className="flex flex-col gap-y-2 border rounded py-2 px-4 mb-2">
                        <UrlConfig
                            logicProps={{
                                logicKey: 'error-tracking-url-triggers',
                                initialUrlTriggerConfig: urlTriggers,
                                onChange: setUrlTriggers,
                            }}
                            title="Enable exception autocapture when URL matches"
                            description="Adding a URL trigger means exception autocapture will only be started when the user visits a page that matches the URL."
                        />
                        <EventTriggers value={eventTriggers} onChange={setEventTriggers} />
                        <LinkedFlagSelector value={linkedFeatureFlag} onChange={setLinkedFeatureFlag} />
                        <Sampling initialValue={sampleRate} onChange={setSampleRate} />
                    </div>
                </div>
            </div>
        </IngestionControls>
    )
}

const Sampling = ({
    initialValue,
    onChange,
}: {
    initialValue: number
    onChange: (sampleRate: ErrorTrackingAutoCaptureControls['sample_rate']) => void
}): JSX.Element => {
    return (
        <div className="space-y-2">
            <LemonLabel className="text-base">Sampling</LemonLabel>
            <IngestionControls.SamplingTrigger initialSampleRate={initialValue * 100} onChange={onChange} />
            <p>Choose how many exceptions to capture. 100% = capture every exception, 50% = capture roughly half.</p>
        </div>
    )
}

function UrlConfig({
    logicProps,
    title,
    description,
}: {
    logicProps: UrlConfigLogicProps
    title: string
    description: string
}): JSX.Element | null {
    const logic = urlConfigLogic(logicProps)
    const {
        isAddUrlTriggerConfigFormVisible,
        urlTriggerConfig,
        editUrlTriggerIndex,
        isProposedUrlTriggerSubmitting,
        checkUrlTrigger,
        checkUrlTriggerResults,
        urlTriggerInputValidationWarning,
    } = useValues(logic)
    const {
        addUrlTrigger,
        newUrlTrigger,
        removeUrlTrigger,
        setEditUrlTriggerIndex,
        cancelProposingUrlTrigger,
        setCheckUrlTrigger,
    } = useActions(logic)

    return (
        <IngestionControls.UrlConfig
            logic={urlConfigLogic}
            logicProps={logicProps}
            formKey="proposedUrlTrigger"
            addUrl={addUrlTrigger}
            validationWarning={urlTriggerInputValidationWarning}
            title={title}
            description={description}
            checkUrl={checkUrlTrigger}
            checkUrlResults={checkUrlTriggerResults}
            setCheckUrl={setCheckUrlTrigger}
            isAddFormVisible={isAddUrlTriggerConfigFormVisible}
            config={urlTriggerConfig}
            editIndex={editUrlTriggerIndex}
            isSubmitting={isProposedUrlTriggerSubmitting}
            onAdd={newUrlTrigger}
            onCancel={cancelProposingUrlTrigger}
            onEdit={setEditUrlTriggerIndex}
            onRemove={removeUrlTrigger}
        />
    )
}

function EventTriggers({
    value,
    onChange,
}: {
    value: ErrorTrackingAutoCaptureControls['event_triggers']
    onChange: (eventTriggers: ErrorTrackingAutoCaptureControls['event_triggers']) => void
}): JSX.Element | null {
    return (
        <div className="flex flex-col space-y-2 mt-2">
            <div className="flex items-center gap-2 justify-between">
                <LemonLabel className="text-base">Event emitted</LemonLabel>
                <IngestionControls.EventTriggerSelect events={value} onChange={onChange} />
            </div>
            <p>Start capturing exceptions when a certain event is queued.</p>

            <div className="flex gap-2 flex-wrap">
                {value.map((trigger) => (
                    <IngestionControls.EventTrigger
                        key={trigger}
                        trigger={trigger}
                        onClose={() => onChange(value?.filter((e) => e !== trigger))}
                    />
                ))}
            </div>
        </div>
    )
}

function LinkedFlagSelector({
    value,
    onChange,
}: {
    value: ErrorTrackingAutoCaptureControls['linked_feature_flag']
    onChange: (linkedFeatureFlag: ErrorTrackingAutoCaptureControls['linked_feature_flag']) => void
}): JSX.Element | null {
    return (
        <IngestionControls.FlagTrigger logicKey="error-tracking-linked-flag" flag={value} onChange={onChange}>
            <div className="flex flex-col space-y-2 mt-2">
                <LemonLabel className="text-base">Feature flag</LemonLabel>
                <IngestionControls.FlagSelector />

                <p>Only capture exceptions when this flag is enabled.</p>
                <IngestionControls.FlagVariantSelector
                    tooltip={<>Choose "any" variant, or only for a specific variant.</>}
                />
            </div>
        </IngestionControls.FlagTrigger>
    )
}
