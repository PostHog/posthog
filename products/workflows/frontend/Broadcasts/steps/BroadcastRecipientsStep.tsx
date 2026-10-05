import { useActions, useMountedLogic, useValues } from 'kea'
import { useState } from 'react'

import { IconUpload, IconWarning } from '@posthog/icons'
import { LemonButton, LemonModal, LemonSelect, Link, Spinner } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { COHORTS_ONLY_SUPPORT_IN_PICKER_PROPS } from 'scenes/feature-flags/cohortPickerProps'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { ActorsQuery, DataTableNode, NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { AnyPersonScopeFilter, PropertyFilterType } from '~/types'

import { optOutCategoriesLogic } from '../../OptOuts/optOutCategoriesLogic'
import { WORKFLOW_OPERATOR_ALLOWLIST } from '../../Workflows/hogflows/filters/HogFlowFilters'
import { BroadcastAudienceCohorts } from '../audience/BroadcastAudienceCohorts'
import { broadcastAudienceListLogic } from '../audience/broadcastAudienceListLogic'
import { BroadcastAudienceListModal } from '../audience/BroadcastAudienceListModal'
import { broadcastWizardLogic } from '../broadcastWizardLogic'

function AudienceSizePreview(): JSX.Element | null {
    const { blastRadius, blastRadiusLoading } = useValues(broadcastWizardLogic)

    if (blastRadiusLoading) {
        return <Spinner className="mt-1" />
    }

    if (!blastRadius) {
        return (
            <div className="text-warning text-xs flex items-center gap-1 mt-1">
                <IconWarning className="text-base shrink-0" />
                <span>Couldn't estimate the audience size. Check your filters and try again.</span>
            </div>
        )
    }

    const { affected, total, limit } = blastRadius
    const exceeded = limit != null && affected > limit

    return (
        <div className="text-muted">
            <span className={exceeded ? 'text-danger font-semibold' : undefined}>
                approximately {humanFriendlyNumber(affected)} of {humanFriendlyNumber(total)} people.
            </span>
            {exceeded && (
                <div className="text-danger text-xs" data-attr="broadcast-audience-over-limit">
                    This project can send a broadcast to up to {humanFriendlyNumber(limit)} people right now. The limit
                    can rise as the project keeps sending with low bounce and spam complaint rates. Add filters to
                    narrow the audience, or{' '}
                    <Link
                        to={urls.workflows('reputation')}
                        target="_blank"
                        data-attr="broadcast-audience-limit-see-sending-limits"
                    >
                        see your sending limits
                    </Link>
                    .
                </div>
            )}
        </div>
    )
}

function MessageCategoryPicker(): JSX.Element {
    const { emailSettings } = useValues(broadcastWizardLogic)
    const { setEmailSettings } = useActions(broadcastWizardLogic)
    const { categories, categoriesLoading } = useValues(optOutCategoriesLogic())
    const selected = categories.find((category) => category.id === emailSettings.messageCategoryId)

    return (
        <div className="flex flex-col gap-1 mt-4">
            <span className="font-semibold">Message category</span>
            <span className="text-secondary text-sm">
                People who unsubscribed from this category don't get the email.{' '}
                <Link to={urls.workflows('opt-outs')} target="_blank">
                    Manage categories
                </Link>
            </span>
            <LemonSelect
                className="max-w-100"
                value={emailSettings.messageCategoryId}
                loading={categoriesLoading}
                onChange={(id) =>
                    setEmailSettings({
                        messageCategoryId: id,
                        messageCategoryType: categories.find((category) => category.id === id)?.category_type ?? null,
                    })
                }
                options={[
                    { value: null, label: 'No category' },
                    ...categories.map((category) => ({
                        value: category.id,
                        label: category.name,
                        labelInMenu: `${category.name} (${category.category_type})`,
                    })),
                ]}
                data-attr="broadcast-message-category"
            />
            {selected?.category_type === 'transactional' && (
                <span className="text-xs text-warning">
                    Transactional emails go to everyone in the audience, including people who unsubscribed.
                </span>
            )}
        </div>
    )
}

function AudienceListTable(): JSX.Element {
    const { audienceProperties } = useValues(broadcastWizardLogic)
    const [query, setQuery] = useState<DataTableNode>(() => ({
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.ActorsQuery,
            tags: { productKey: ProductKey.WORKFLOWS, scene: Scene.Broadcast },
            select: ['person_display_name -- Person', 'properties.email -- Email', 'created_at'],
            properties: audienceProperties as AnyPersonScopeFilter[],
            orderBy: ['created_at DESC'],
        } as ActorsQuery,
        full: false,
        showSearch: true,
    }))

    return <DataTable query={query} setQuery={setQuery} uniqueKey="broadcast-audience-list" readOnly />
}

function AudienceListModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }): JSX.Element {
    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="People who match now"
            description="The list updates at send time. People who share an email address get one email."
            width={900}
        >
            {/* Mounted per open, so the list always reflects the current conditions. */}
            {isOpen && <AudienceListTable />}
        </LemonModal>
    )
}

export function BroadcastRecipientsStep(): JSX.Element {
    const { audienceProperties } = useValues(broadcastWizardLogic)
    const { setAudienceProperties } = useActions(broadcastWizardLogic)
    const { props } = useMountedLogic(broadcastWizardLogic)
    const { openListModal } = useActions(broadcastAudienceListLogic(props))
    const [audienceListOpen, setAudienceListOpen] = useState(false)

    return (
        <div className="flex flex-col gap-2">
            <div>
                <h2 className="m-0 text-xl font-semibold">Who should receive this email?</h2>
                <p className="m-0 text-secondary">
                    Filter by person properties or cohorts, or upload a list. Without filters, the broadcast goes to
                    everyone.
                </p>
            </div>
            <div className="flex items-start justify-between gap-2">
                <div>
                    <span className="font-semibold">This broadcast will reach</span> <AudienceSizePreview />
                </div>
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={() => setAudienceListOpen(true)}
                    data-attr="broadcast-audience-view-list"
                >
                    View list
                </LemonButton>
            </div>
            <AudienceListModal isOpen={audienceListOpen} onClose={() => setAudienceListOpen(false)} />
            <PropertyFilters
                pageKey="broadcast-wizard-recipients"
                propertyFilters={audienceProperties}
                addText="Add condition"
                orFiltering
                sendAllKeyUpdates
                allowRelativeDateOptions
                {...COHORTS_ONLY_SUPPORT_IN_PICKER_PROPS}
                hideBehavioralCohorts
                logicalRowDivider
                onChange={(properties) => setAudienceProperties(properties)}
                taxonomicGroupTypes={[
                    TaxonomicFilterGroupType.PersonProperties,
                    TaxonomicFilterGroupType.Cohorts,
                    TaxonomicFilterGroupType.Metadata,
                ]}
                taxonomicFilterOptionsFromProp={{
                    [TaxonomicFilterGroupType.Metadata]: [
                        { name: 'distinct_id', propertyFilterType: PropertyFilterType.Person },
                    ],
                }}
                hasRowOperator={false}
                operatorAllowlist={WORKFLOW_OPERATOR_ALLOWLIST}
            />
            <div>
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconUpload />}
                    onClick={openListModal}
                    data-attr="broadcast-audience-add-list"
                >
                    Upload a list
                </LemonButton>
            </div>
            <BroadcastAudienceCohorts />
            <BroadcastAudienceListModal />
            <MessageCategoryPicker />
        </div>
    )
}
