import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { CyclotronJobInputIntegration } from 'lib/components/CyclotronJob/integrations/CyclotronJobInputIntegration'
import { CyclotronJobInputIntegrationField } from 'lib/components/CyclotronJob/integrations/CyclotronJobInputIntegrationField'
import { LemonField } from 'lib/lemon-ui/LemonField/LemonField'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { HogFunctionIcon } from 'scenes/hog-functions/configuration/HogFunctionIcon'

import { CyclotronJobInputSchemaType } from '~/types'

import {
    DestinationOption,
    TRIGGER_OPTIONS,
    TriggerOption,
    errorTrackingAlertWizardLogic,
} from './errorTrackingAlertWizardLogic'

function WizardCard({
    icon,
    name,
    description,
    onClick,
}: {
    icon?: React.ReactNode
    name: string
    description: string
    onClick: () => void
}): JSX.Element {
    return (
        <button
            type="button"
            onClick={onClick}
            className={clsx(
                'group relative text-left rounded-lg border border-border bg-bg-light transition-all cursor-pointer p-5 w-full',
                'hover:border-border-bold hover:shadow-sm',
                'focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2'
            )}
        >
            <div className="flex items-center gap-4">
                {icon && <div className="shrink-0">{icon}</div>}
                <div>
                    <h3 className="font-semibold text-base mb-0.5 transition-colors group-hover:text-link">{name}</h3>
                    <p className="text-secondary text-sm mb-0">{description}</p>
                </div>
            </div>
        </button>
    )
}

function DestinationStep({ onBack }: { onBack: () => void }): JSX.Element {
    const { destinationOptions, existingAlertsLoading } = useValues(errorTrackingAlertWizardLogic)
    const { setDestination } = useActions(errorTrackingAlertWizardLogic)

    if (existingAlertsLoading) {
        return (
            <div className="space-y-4">
                <div>
                    <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} onClick={onBack}>
                        Alerts list
                    </LemonButton>
                    <h2 className="text-xl font-semibold mb-1 mt-2">Where should we send alerts?</h2>
                    <p className="text-secondary text-sm">Choose your preferred notification channel</p>
                </div>
                <div className="space-y-3">
                    {[1, 2, 3].map((i) => (
                        <div key={i} className="rounded-lg border border-border bg-bg-light animate-pulse p-5 w-full">
                            <div className="flex items-center gap-4">
                                <div className="shrink-0 w-10 h-10 rounded bg-border" />
                                <div className="flex-1 space-y-2">
                                    <div className="h-4 w-24 rounded bg-border" />
                                    <div className="h-3 w-48 rounded bg-border" />
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        )
    }

    return (
        <div className="space-y-4">
            <div>
                <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} onClick={onBack}>
                    Alerts list
                </LemonButton>
                <h2 className="text-xl font-semibold mb-1 mt-2">Where should we send alerts?</h2>
                <p className="text-secondary text-sm">Choose your preferred notification channel</p>
            </div>
            <div className="space-y-3">
                {destinationOptions.map((option: DestinationOption) => (
                    <WizardCard
                        key={option.key}
                        icon={<HogFunctionIcon src={option.icon} size="medium" />}
                        name={option.name}
                        description={option.description}
                        onClick={() => setDestination(option.key)}
                    />
                ))}
            </div>
        </div>
    )
}

function TriggerStep(): JSX.Element {
    const { setTrigger, setStep } = useActions(errorTrackingAlertWizardLogic)

    return (
        <div className="space-y-4">
            <div>
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconArrowLeft />}
                    onClick={() => setStep('destination')}
                >
                    Choose destination
                </LemonButton>
                <h2 className="text-xl font-semibold mb-1 mt-2">What should trigger the alert?</h2>
                <p className="text-secondary text-sm">Choose when you want to be notified</p>
            </div>
            <div className="space-y-3">
                {TRIGGER_OPTIONS.map((option: TriggerOption) => (
                    <WizardCard
                        key={option.key}
                        name={option.name}
                        description={option.description}
                        onClick={() => setTrigger(option.key)}
                    />
                ))}
            </div>
        </div>
    )
}

function ConfigureStep(): JSX.Element {
    const { requiredInputsSchema, configuration, selectedTemplateLoading, submitting } =
        useValues(errorTrackingAlertWizardLogic)
    const { setStep, setInputValue, submitConfiguration } = useActions(errorTrackingAlertWizardLogic)

    if (selectedTemplateLoading) {
        return (
            <div className="space-y-4">
                <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} onClick={() => setStep('trigger')}>
                    Choose trigger
                </LemonButton>
                <h2 className="text-xl font-semibold mb-1 mt-2">Configure your alert</h2>
                <LemonSkeleton className="h-10" />
                <LemonSkeleton className="h-10" />
            </div>
        )
    }

    return (
        <div className="space-y-4">
            <div>
                <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} onClick={() => setStep('trigger')}>
                    Choose trigger
                </LemonButton>
                <h2 className="text-xl font-semibold mb-1 mt-2">Configure your alert</h2>
                <p className="text-secondary text-sm">Fill in the details to complete setup</p>
            </div>

            <div className="space-y-4">
                {requiredInputsSchema.map((schema: CyclotronJobInputSchemaType) => (
                    <LemonField.Pure key={schema.key} label={schema.label}>
                        <SchemaInput
                            schema={schema}
                            value={configuration.inputs?.[schema.key]?.value}
                            onChange={(val) => setInputValue(schema.key, { value: val })}
                            configuration={configuration}
                            onInputChange={setInputValue}
                        />
                    </LemonField.Pure>
                ))}
            </div>

            <div className="flex justify-end">
                <LemonButton type="primary" onClick={submitConfiguration} loading={submitting}>
                    Create alert
                </LemonButton>
            </div>
        </div>
    )
}

function SchemaInput({
    schema,
    value,
    onChange,
    configuration,
    onInputChange,
}: {
    schema: CyclotronJobInputSchemaType
    value: any
    onChange: (value: any) => void
    configuration: { inputs_schema: CyclotronJobInputSchemaType[]; inputs: Record<string, any> | null }
    onInputChange: (key: string, value: any) => void
}): JSX.Element {
    if (schema.type === 'integration') {
        return (
            <CyclotronJobInputIntegration
                schema={schema}
                value={value}
                onChange={(newValue) => {
                    configuration.inputs_schema
                        .filter((s) => s.type === 'integration_field' && s.integration_key === schema.key)
                        .forEach((field) => {
                            onInputChange(field.key, { value: null })
                        })
                    onChange(newValue)
                }}
            />
        )
    }

    if (schema.type === 'integration_field') {
        return (
            <CyclotronJobInputIntegrationField
                schema={schema}
                value={value}
                onChange={onChange}
                configuration={configuration}
            />
        )
    }

    return <LemonInput value={value ?? ''} onChange={onChange} placeholder={schema.description || schema.label || ''} />
}

export interface ErrorTrackingAlertWizardProps {
    onCancel: () => void
    onSwitchToTraditional: () => void
}

export function ErrorTrackingAlertWizard({
    onCancel,
    onSwitchToTraditional,
}: ErrorTrackingAlertWizardProps): JSX.Element {
    const { currentStep } = useValues(errorTrackingAlertWizardLogic)

    return (
        <div className="flex flex-col min-h-[400px]">
            <div className="max-w-lg mx-auto flex-1 w-full">
                {currentStep === 'destination' && <DestinationStep onBack={onCancel} />}
                {currentStep === 'trigger' && <TriggerStep />}
                {currentStep === 'configure' && <ConfigureStep />}
            </div>

            <p className="text-center text-xs text-muted mt-6">
                Need more control?{' '}
                <button type="button" onClick={onSwitchToTraditional} className="text-link hover:underline">
                    Go back to traditional editor
                </button>
            </p>
        </div>
    )
}
