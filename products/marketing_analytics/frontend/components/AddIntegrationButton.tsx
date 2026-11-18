import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuItems } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { FEATURE_FLAGS, TeamMembershipLevel } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'
import { urls } from 'scenes/urls'
import {
    VALID_FILE_MARKETING_SOURCES,
    VALID_WAREHOUSE_MARKETING_SOURCES,
    getEnabledNativeMarketingSources,
    marketingSourceDisplayLabel,
    nativeSourceDisplayLabel,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/utils'

import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

import { newAdSourcesLogic } from './newAdSourcesLogic'
import { QuillAddIntegrationButton } from './QuillAddIntegrationButton'

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
    const [showNoticeInMenu, setShowNoticeInMenu] = useState(false)
    const quillSurface = useQuillSurface()
    const showNewSources = showNotice && !restrictedReason
    const showNewSourcesInMenu = showNoticeInMenu && newSources.length > 0 && !restrictedReason

    const handleVisibilityChange = (visible: boolean): void => {
        setShowPopover(visible)
        setShowNoticeInMenu(visible && showNewSources)
        if (visible && showNewSources) {
            dismissNotice()
        }
    }

    const handleIntegrateClick = (integrationId: string): void => {
        onIntegrationSelect?.(integrationId)
        handleVisibilityChange(false)
    }

    const groups = [
        { title: 'Native integrations', sources: getEnabledNativeMarketingSources(featureFlags) },
        ...(featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_ORGANIC_KEYWORDS]
            ? [{ title: 'Organic search', sources: ['GoogleSearchConsole'] }]
            : []),
        { title: 'External sources', sources: VALID_WAREHOUSE_MARKETING_SOURCES },
        { title: 'Files', sources: VALID_FILE_MARKETING_SOURCES },
    ]
    const visibleGroups = groups.filter(({ sources }) => sources.length > 0)
    const newSourcesNotice = `Connect ${newSources.map(nativeSourceDisplayLabel).join(', ')} to compare spend and conversions.`

    const integrationLabel = (integrationId: string): string =>
        integrationId === 'GoogleSearchConsole' ? 'Google Search Console' : marketingSourceDisplayLabel(integrationId)

    const isNewSource = (integrationId: string): boolean =>
        showNewSourcesInMenu && newSources.some((source) => source === integrationId)

    const integrationUrl = (integrationId: string): string | undefined =>
        onIntegrationSelect
            ? undefined
            : urls.dataWarehouseSourceNew(
                  integrationId,
                  urls.marketingAnalyticsApp(),
                  'Marketing analytics',
                  undefined,
                  'marketing_analytics_integration_menu'
              )

    if (quillSurface) {
        return (
            <QuillAddIntegrationButton
                open={showPopover}
                onOpenChange={handleVisibilityChange}
                groups={visibleGroups}
                newSourcesNotice={showNewSourcesInMenu ? newSourcesNotice : null}
                showNewSources={showNewSources}
                restrictedReason={restrictedReason}
                integrationLabel={integrationLabel}
                isNewSource={isNewSource}
                integrationUrl={integrationUrl}
                onIntegrate={handleIntegrateClick}
            />
        )
    }

    const items: LemonMenuItems = [
        ...(showNewSourcesInMenu
            ? [
                  {
                      key: 'new-ad-sources',
                      title: (
                          <div className="w-72 max-w-full p-2 space-y-2">
                              <div className="font-semibold">New ad sources</div>
                              <p className="m-0 text-muted text-sm">{newSourcesNotice}</p>
                          </div>
                      ),
                      items: [],
                  },
              ]
            : []),
        ...visibleGroups.map(({ title, sources }) => ({
            title,
            items: sources.map((integrationId) => ({
                key: integrationId,
                label: integrationLabel(integrationId),
                icon: <SourceIcon type={integrationId} size="xsmall" disableTooltip />,
                tag: isNewSource(integrationId) ? ('new' as const) : undefined,
                disabledReason: restrictedReason,
                to: integrationUrl(integrationId),
                onClick: () => handleIntegrateClick(integrationId),
            })),
        })),
    ]

    return (
        <LemonMenu
            items={items}
            visible={showPopover}
            onVisibilityChange={handleVisibilityChange}
            focusBasedKeyboardNavigation={showPopover}
            closeOnClickInside={false}
            placement="bottom-end"
            maxContentWidth
        >
            <LemonButton
                type="primary"
                size="small"
                icon={<IconPlusSmall />}
                data-attr="add-integration"
                aria-label="Add source"
                disabledReason={restrictedReason}
                tooltip={restrictedReason ? undefined : 'New ad sources are available'}
                tooltipForceMount={restrictedReason || (showNewSources && !showPopover) ? undefined : false}
            >
                <span>Add source</span>
            </LemonButton>
        </LemonMenu>
    )
}
