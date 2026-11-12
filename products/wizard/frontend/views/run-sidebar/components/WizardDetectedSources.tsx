import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { availableSourcesLogic } from 'products/data_warehouse/frontend/scenes/NewSourceScene/availableSourcesLogic'
import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

import type { WizardDetectedWarehouseSourceApi } from '../../../generated/api.schemas'

export function WizardDetectedSources({
    sources,
    onSourceClick,
}: {
    sources: WizardDetectedWarehouseSourceApi[]
    onSourceClick: (sourceType: string) => void
}): JSX.Element {
    const { availableSources } = useValues(availableSourcesLogic)
    return (
        <section
            aria-labelledby="wizard-detected-sources-heading"
            className="border-t border-primary px-3 py-2"
            data-attr="wizard-detected-sources"
        >
            <p id="wizard-detected-sources-heading" className="mb-0 text-xs font-semibold">
                Found in your codebase
            </p>
            <p className="mb-1 text-2xs text-muted">
                Connect these data sources to query them next to your product data.
            </p>
            <ul className="m-0 list-none p-0">
                {sources.map((source) => (
                    <li key={source.warehouse_source_type} className="flex items-center gap-2 py-0.5">
                        <SourceIcon type={source.warehouse_source_type} size="xsmall" disableTooltip />
                        <span className="min-w-0 flex-1 truncate text-sm">
                            {availableSources?.[source.warehouse_source_type]?.label ?? source.warehouse_source_type}
                        </span>
                        <LemonButton
                            type="secondary"
                            size="xsmall"
                            to={urls.dataWarehouseSourceNew(source.warehouse_source_type)}
                            onClick={() => onSourceClick(source.warehouse_source_type)}
                            data-attr="wizard-detected-source-connect"
                        >
                            Connect
                        </LemonButton>
                    </li>
                ))}
            </ul>
        </section>
    )
}
