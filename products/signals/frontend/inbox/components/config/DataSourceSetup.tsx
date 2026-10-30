import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { availableSourcesLogic } from 'products/data_warehouse/frontend/scenes/NewSourceScene/availableSourcesLogic'
import { sourceWizardLogic } from 'products/data_warehouse/frontend/scenes/NewSourceScene/sourceWizardLogic'
import SourceForm from 'products/data_warehouse/frontend/shared/components/forms/SourceForm'
import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'
import { SourceConfigResponseApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { WAREHOUSE_SOURCE_SETUP, WarehouseBackedSource } from '../../signalSourcesLogic'

/** Connect-a-warehouse-source flow for a signal source; tables and wizard product come from its registration. */
export function DataSourceSetup({
    source,
    onComplete,
    onCancel,
    completing = false,
    oauthRedirectUrl,
    cancelLabel = 'Back to signals',
}: {
    source: WarehouseBackedSource
    onComplete: () => void
    onCancel?: () => void
    completing?: boolean
    oauthRedirectUrl?: string
    cancelLabel?: string
}): JSX.Element {
    const { availableSources, availableSourcesLoading } = useValues(availableSourcesLogic)
    const { load } = useActions(availableSourcesLogic)
    const { dwSourceType, requiredTables, requiredTableSyncType } = WAREHOUSE_SOURCE_SETUP[source]

    const sourceConfig = availableSources
        ? Object.values(availableSources).find((s: SourceConfigResponseApi) => s.name === dwSourceType)
        : undefined
    if (!sourceConfig) {
        return (
            <div className="space-y-4">
                {onCancel && (
                    <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} onClick={onCancel}>
                        {cancelLabel}
                    </LemonButton>
                )}
                {availableSourcesLoading ? (
                    <LemonSkeleton />
                ) : (
                    <LemonBanner type="error">
                        <p>Could not load this connection form. Check your access to data sources and try again.</p>
                        <LemonButton size="small" onClick={load}>
                            Retry
                        </LemonButton>
                    </LemonBanner>
                )}
            </div>
        )
    }

    return (
        <BindLogic
            logic={sourceWizardLogic}
            props={{
                availableSources,
                requiredTables,
                requiredTableSyncType,
                onComplete,
                oauthRedirectUrl,
            }}
        >
            <DataSourceSetupForm
                sourceConfig={sourceConfig}
                onCancel={onCancel}
                cancelLabel={cancelLabel}
                completing={completing}
            />
        </BindLogic>
    )
}

function DataSourceSetupForm({
    sourceConfig,
    onCancel,
    cancelLabel,
    completing,
}: {
    sourceConfig: SourceConfigResponseApi
    onCancel?: () => void
    cancelLabel: string
    completing: boolean
}): JSX.Element {
    const { isLoading, canGoNext } = useValues(sourceWizardLogic)
    const { setInitialConnector, onSubmit } = useActions(sourceWizardLogic)

    useEffect(() => {
        setInitialConnector(sourceConfig)
    }, []) // eslint-disable-line react-hooks/exhaustive-deps

    return (
        <div className="space-y-4">
            {onCancel && (
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconArrowLeft />}
                    onClick={onCancel}
                    disabled={isLoading || completing}
                >
                    {cancelLabel}
                </LemonButton>
            )}
            <div className="flex items-center gap-3">
                <SourceIcon type={sourceConfig.name} size="small" disableTooltip />
                <p className="text-sm text-muted-alt mb-0">
                    Connect {sourceConfig.label ?? sourceConfig.name} as a data source to enable this signal.
                </p>
            </div>

            <SourceForm sourceConfig={sourceConfig} showPrefix={false} />

            <div className="flex justify-end">
                <LemonButton
                    type="primary"
                    loading={isLoading || completing}
                    disabledReason={!canGoNext ? 'Fill in the required fields' : undefined}
                    onClick={() => onSubmit()}
                >
                    Connect
                </LemonButton>
            </div>
        </div>
    )
}
