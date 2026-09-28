import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuItems, LemonTag } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'
import {
    VALID_NON_NATIVE_MARKETING_SOURCES,
    VALID_SELF_MANAGED_MARKETING_SOURCES,
    getEnabledNativeMarketingSources,
    nativeSourceDisplayLabel,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/utils'

import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

import { newAdSourcesLogic } from './newAdSourcesLogic'

interface AddIntegrationButtonProps {
    onIntegrationSelect?: (integrationId: string) => void
}

export function AddIntegrationButton({ onIntegrationSelect }: AddIntegrationButtonProps = {}): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { newSources, showNotice } = useValues(newAdSourcesLogic)
    const { dismissNotice } = useActions(newAdSourcesLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const [showPopover, setShowPopover] = useState(false)
    const showNewSources = showNotice && !restrictedReason

    const handleIntegrateClick = (integrationId: string): void => {
        if (onIntegrationSelect) {
            onIntegrationSelect(integrationId)
        } else {
            router.actions.push(
                urls.dataWarehouseSourceNew(integrationId, urls.marketingAnalyticsApp(), 'Marketing analytics')
            )
        }
        setShowPopover(false)
    }

    const groups = [
        { title: 'Native integrations', sources: getEnabledNativeMarketingSources(featureFlags) },
        { title: 'External sources', sources: VALID_NON_NATIVE_MARKETING_SOURCES },
        { title: 'Self-managed sources', sources: VALID_SELF_MANAGED_MARKETING_SOURCES },
    ]
    const items: LemonMenuItems = [
        showNewSources && {
            items: [
                {
                    key: 'new-ad-sources',
                    label: () => (
                        <div className="w-72 max-w-full p-2 space-y-2">
                            <div className="font-semibold">New ad sources</div>
                            <p className="m-0 text-muted text-sm">
                                {`Connect ${newSources.map(nativeSourceDisplayLabel).join(', ')} to compare spend and conversions.`}
                            </p>
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                onClick={dismissNotice}
                                data-attr="marketing-new-ad-sources-dismiss"
                            >
                                Got it
                            </LemonButton>
                        </div>
                    ),
                },
            ],
        },
        ...groups
            .filter(({ sources }) => sources.length > 0)
            .map(({ title, sources }) => ({
                title,
                items: sources.map((integrationId) => ({
                    key: integrationId,
                    label: nativeSourceDisplayLabel(integrationId),
                    icon: <SourceIcon type={integrationId} size="xsmall" disableTooltip />,
                    tag:
                        showNewSources && newSources.some((source) => source === integrationId)
                            ? ('new' as const)
                            : undefined,
                    disabledReason: restrictedReason,
                    onClick: () => handleIntegrateClick(integrationId),
                })),
            })),
    ]

    return (
        <LemonMenu
            items={items}
            visible={showPopover}
            onVisibilityChange={setShowPopover}
            closeOnClickInside={false}
            placement="bottom-end"
            maxContentWidth
        >
            <LemonButton
                type="primary"
                size="small"
                icon={<IconPlusSmall />}
                data-attr="add-integration"
                disabledReason={restrictedReason}
                tooltip={showNewSources && !showPopover ? 'New ad sources are available' : undefined}
            >
                <span>Add source</span>
                {showNewSources && (
                    <LemonTag type="option" size="small" className="ml-2">
                        New
                    </LemonTag>
                )}
            </LemonButton>
        </LemonMenu>
    )
}
