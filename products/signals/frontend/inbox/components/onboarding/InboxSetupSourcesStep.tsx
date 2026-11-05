import { useActions, useValues } from 'kea'

import { LemonButton, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { GuidedWizardSection } from 'lib/components/GuidedWizard/GuidedWizardSection'

import { inboxSetupLogic } from '../../logics/inboxSetupLogic'
import { signalSourcesLogic } from '../../signalSourcesLogic'
import { getSourceProductMeta } from '../badges/sourceProductIcons'
import { AutonomySettingGroup } from '../config/AutonomySettingGroup'
import { AutonomySettingRow } from '../config/AutonomySettingRow'

export function InboxSetupSourcesStep(): JSX.Element {
    const { sources, draft, ready, saving } = useValues(inboxSetupLogic)
    const { toggleSource } = useActions(inboxSetupLogic)
    const { productStatusBySource, enablingProduct } = useValues(signalSourcesLogic)
    const { enableSourceProduct } = useActions(signalSourcesLogic)
    const productsNeedingSetup = sources.filter((source) => !source.available)
    return (
        <GuidedWizardSection
            title="Choose what to watch"
            description="Signals from these sources tell Self-Driving when something needs a closer look."
            descriptionClassName="text-sm"
        >
            {!ready ? (
                <LemonSkeleton className="h-40" />
            ) : (
                <>
                    <div className="divide-y border-primary">
                        {sources
                            .filter((source) => source.available)
                            .map((source) => {
                                const Icon = getSourceProductMeta(source.definition.sourceProduct)?.Icon
                                const checked =
                                    source.definition.source === 'replay_vision'
                                        ? draft.scanner_ids.length > 0
                                        : draft.sources.some(
                                              (item) =>
                                                  item.source_product === source.definition.sourceProduct &&
                                                  item.enabled
                                          )
                                return (
                                    <div key={source.definition.source} className="flex items-center gap-3 py-4">
                                        {Icon && <Icon className="text-xl shrink-0" />}
                                        <div className="flex-1 min-w-0">
                                            <h3 className="m-0 text-sm font-semibold">{source.definition.label}</h3>
                                            <p className="m-0 text-xs text-secondary">{source.definition.watches}</p>
                                        </div>
                                        <LemonSwitch
                                            checked={checked}
                                            onChange={(enabled) => toggleSource(source, enabled)}
                                            disabled={saving}
                                            aria-label={`Enable ${source.definition.label}`}
                                            data-attr={`inbox-setup-source-${source.definition.source}`}
                                        />
                                    </div>
                                )
                            })}
                    </div>
                    {!sources.some((source) => source.available) && (
                        <p>
                            No products are sending usable signals yet. Enable a product below or choose a scout in the
                            next step. You need at least one source or scout to activate Self-Driving.
                        </p>
                    )}
                    {productsNeedingSetup.length > 0 && (
                        <section className="border-t border-primary pt-4">
                            <AutonomySettingGroup title="Products that need setup">
                                {productsNeedingSetup.map((source) => {
                                    const product = productStatusBySource[source.definition.source]
                                    return (
                                        <AutonomySettingRow
                                            key={source.definition.source}
                                            title={source.definition.label}
                                            description={
                                                source.unavailableReason === 'Not enabled'
                                                    ? source.definition.watches
                                                    : source.unavailableReason
                                            }
                                            control={
                                                product?.enabled === false && product.enablement ? (
                                                    <LemonButton
                                                        type="secondary"
                                                        size="small"
                                                        loading={enablingProduct === product.enablement}
                                                        disabledReason={
                                                            saving ||
                                                            (enablingProduct !== null &&
                                                                enablingProduct !== product.enablement)
                                                                ? 'Finishing setup changes'
                                                                : undefined
                                                        }
                                                        onClick={() => enableSourceProduct(product.enablement!)}
                                                    >
                                                        {`Turn on ${product.productName}`}
                                                    </LemonButton>
                                                ) : source.definition.manageUrl || source.definition.docsUrl ? (
                                                    <LemonButton
                                                        type="secondary"
                                                        size="small"
                                                        targetBlank
                                                        to={source.definition.manageUrl ?? source.definition.docsUrl}
                                                    >
                                                        {source.definition.source === 'replay_vision'
                                                            ? 'Create scanner'
                                                            : 'Set up'}
                                                    </LemonButton>
                                                ) : null
                                            }
                                        />
                                    )
                                })}
                            </AutonomySettingGroup>
                            <p className="text-xs text-secondary mt-4 mb-0">
                                You can add more sources after activation.
                            </p>
                        </section>
                    )}
                </>
            )}
        </GuidedWizardSection>
    )
}
