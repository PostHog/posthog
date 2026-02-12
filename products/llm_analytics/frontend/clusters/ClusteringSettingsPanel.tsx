import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { clusteringConfigLogic } from './clusteringConfigLogic'

export function ClusteringSettingsPanel(): JSX.Element {
    const { isSettingsPanelOpen, localEventFilters, configLoading } = useValues(clusteringConfigLogic)
    const { closeSettingsPanel, setLocalEventFilters, saveEventFilters } = useActions(clusteringConfigLogic)

    return (
        <LemonModal
            isOpen={isSettingsPanelOpen}
            onClose={closeSettingsPanel}
            title="Clustering settings"
            description="Configure event filters applied to both summarization and clustering pipelines."
            footer={
                <>
                    <div className="flex-1" />
                    <LemonButton type="secondary" onClick={closeSettingsPanel} data-attr="clustering-settings-cancel">
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={saveEventFilters}
                        loading={configLoading}
                        data-attr="clustering-settings-save"
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-4">
                <div>
                    <h4 className="font-semibold mb-3">Event filters</h4>
                    <div className="text-sm text-muted mb-3">
                        Only include traces matching these criteria in automated summarization and clustering. Leave
                        empty to include all traces.
                    </div>
                    <PropertyFilters
                        propertyFilters={localEventFilters}
                        onChange={(properties) => setLocalEventFilters(properties)}
                        pageKey="clustering-config-event-filters"
                        taxonomicGroupTypes={[
                            TaxonomicFilterGroupType.EventProperties,
                            TaxonomicFilterGroupType.EventMetadata,
                        ]}
                        addText="Add event filter"
                        hasRowOperator={false}
                        sendAllKeyUpdates
                        allowRelativeDateOptions={false}
                    />
                    <div className="text-xs text-muted mt-2">
                        <strong>Examples:</strong> $ai_model = "gpt-4", $ai_provider = "openai", ai_product =
                        "posthog_ai"
                    </div>
                </div>
            </div>
        </LemonModal>
    )
}
