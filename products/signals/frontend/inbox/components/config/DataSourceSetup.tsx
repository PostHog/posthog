import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

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
}: {
    source: WarehouseBackedSource
    onComplete: () => void
}): JSX.Element {
    const { availableSources, availableSourcesLoading } = useValues(availableSourcesLogic)
    const { load } = useActions(availableSourcesLogic)
    const { dwSourceType, requiredTables } = WAREHOUSE_SOURCE_SETUP[source]

    if (availableSourcesLoading) {
        return <LemonSkeleton className="h-16" />
    }

    // The wizard endpoint answers 403 without an error, so an empty list also covers "not allowed".
    if (availableSources === null) {
        return (
            <SetupUnavailable onRetry={load}>
                Couldn't load the data sources you can connect. You may not have permission to add one in this project,
                so check with an admin if trying again doesn't help.
            </SetupUnavailable>
        )
    }

    const sourceConfig = Object.values(availableSources).find((s: SourceConfigResponseApi) => s.name === dwSourceType)
    if (!sourceConfig) {
        return (
            <SetupUnavailable onRetry={load}>
                This data source isn't available to connect from here. You can{' '}
                <Link to={urls.dataWarehouseSourceNew()}>add it in the data warehouse</Link>, then turn this source on.
            </SetupUnavailable>
        )
    }

    return (
        <BindLogic
            logic={sourceWizardLogic}
            props={{
                availableSources,
                requiredTables,
                onComplete,
            }}
        >
            <DataSourceSetupForm sourceConfig={sourceConfig} />
        </BindLogic>
    )
}

function SetupUnavailable({ children, onRetry }: { children: React.ReactNode; onRetry: () => void }): JSX.Element {
    return (
        <div className="flex flex-col items-start gap-2 rounded border border-dashed p-4">
            <p className="mb-0 text-sm text-secondary">{children}</p>
            <LemonButton type="secondary" size="small" onClick={onRetry}>
                Try again
            </LemonButton>
        </div>
    )
}

function DataSourceSetupForm({ sourceConfig }: { sourceConfig: SourceConfigResponseApi }): JSX.Element {
    const { isLoading, canGoNext } = useValues(sourceWizardLogic)
    const { setInitialConnector, onSubmit } = useActions(sourceWizardLogic)

    useEffect(() => {
        setInitialConnector(sourceConfig)
    }, []) // eslint-disable-line react-hooks/exhaustive-deps

    return (
        <div className="space-y-4">
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
                    loading={isLoading}
                    disabledReason={!canGoNext ? 'Fill in the required fields' : undefined}
                    onClick={() => onSubmit()}
                >
                    Connect
                </LemonButton>
            </div>
        </div>
    )
}
