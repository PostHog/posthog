import { useValues } from 'kea'
import { useState } from 'react'

import { IconCheckCircle, IconDatabase, IconPieChart, IconPlus } from '@posthog/icons'
import { LemonButton, LemonCard, Link } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { NewSourcesWizard } from 'scenes/data-warehouse/new/NewSourceWizard'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'

import { ExternalDataSourceType } from '~/queries/schema/schema-general'

import { EventConfigurationModal } from '../settings/EventConfigurationModal'
import { revenueAnalyticsSettingsLogic } from '../settings/revenueAnalyticsSettingsLogic'

interface RevenueSource {
    id: ExternalDataSourceType
    description: string
    isAvailable: boolean
    isConnected: boolean
}

interface InlineSetupProps {
    closeOnboarding: () => void
    initialSetupView?: InlineSetupView // NOTE: This should NOT be used except for testing purposes (storybook)
}

export type InlineSetupView = 'overview' | 'add-source'

// These are all the future revenue sources that are displayed,
// and then under it we restrict to the ones which we've actually implemented with Revenue Analytics
const REVENUE_SOURCE_TYPES: ExternalDataSourceType[] = ['Stripe', 'Chargebee', 'Polar', 'RevenueCat']
const AVAILABLE_REVENUE_SOURCE_TYPES: Set<ExternalDataSourceType> = new Set(['Stripe'])

export function InlineSetup({ closeOnboarding, initialSetupView }: InlineSetupProps): JSX.Element {
    const { events, enabledDataWarehouseSources } = useValues(revenueAnalyticsSettingsLogic)

    const hasEvents = events.length > 0
    const hasSources = enabledDataWarehouseSources.length > 0

    const [currentView, setCurrentView] = useState<InlineSetupView>(initialSetupView ?? 'overview')
    const [selectedSource, setSelectedSource] = useState<ExternalDataSourceType | null>(null)
    const [showEventModal, setShowEventModal] = useState(false)

    const revenueSources: RevenueSource[] = REVENUE_SOURCE_TYPES.map((source_type) => ({
        id: source_type,
        description: `Import revenue data from ${source_type}`,
        isAvailable: AVAILABLE_REVENUE_SOURCE_TYPES.has(source_type),
        isConnected: enabledDataWarehouseSources.some((source) => source.source_type === source_type),
    }))

    const handleSourceSelect = (sourceId: ExternalDataSourceType): void => {
        const source = revenueSources.find((s) => s.id === sourceId)
        if (!source) {
            return
        }

        setSelectedSource(sourceId)
        setCurrentView('add-source')
    }

    const handleFormSuccess = (): void => {
        setCurrentView('overview')
        setSelectedSource(null)
    }

    const handleEventModalClose = (): void => {
        setShowEventModal(false)
    }

    return (
        <div className="space-y-6">
            {/* Main Setup Card */}
            <LemonCard hoverEffect={false}>
                <div className="space-y-4">
                    <div className="flex items-center justify-between">
                        <div>
                            <h3 className="text-lg font-semibold mb-1">Revenue Analytics Setup</h3>
                            <p className="text-sm text-muted-alt">Configure your revenue tracking to get started</p>
                        </div>
                        {(hasEvents || hasSources) && (
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={closeOnboarding}
                                icon={<IconCheckCircle />}
                            >
                                View Dashboard
                            </LemonButton>
                        )}
                    </div>

                    {/* Current Status */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {/* Events Status */}
                        <div className="flex items-center gap-3 p-3 rounded-lg border border-primary">
                            <div className="flex items-center justify-center w-10 h-10 rounded-full bg-bg-light border border-primary">
                                {hasEvents ? (
                                    <IconCheckCircle className="w-6 h-6" />
                                ) : (
                                    <IconPieChart className="w-6 h-6 text-muted" />
                                )}
                            </div>
                            <div className="flex-1">
                                <span className="font-medium text-sm">
                                    {hasEvents
                                        ? `${events.length} Event${events.length !== 1 ? 's' : ''} Configured`
                                        : 'No Events Configured'}
                                </span>
                                <p className="text-xs text-muted-alt mt-0.5">
                                    {hasEvents ? 'Revenue events are set up' : 'Configure events to track revenue'}
                                </p>
                            </div>
                        </div>

                        {/* Sources Status */}
                        <div className="flex items-center gap-3 p-3 rounded-lg border border-primary">
                            <div className="flex items-center justify-center w-10 h-10 rounded-full bg-bg-light border border-primary">
                                {hasSources ? (
                                    <IconCheckCircle className="w-6 h-6" />
                                ) : (
                                    <IconDatabase className="w-6 h-6 text-muted" />
                                )}
                            </div>
                            <div className="flex-1">
                                <span className="font-medium text-sm">
                                    {hasSources ? 'Revenue source connected' : 'No revenue sources connected'}
                                </span>
                                <p className="text-xs text-muted-alt mt-0.5">
                                    {hasSources
                                        ? 'Revenue data source is set up'
                                        : 'Connect Stripe to import revenue data'}
                                </p>
                            </div>
                        </div>
                    </div>

                    {/* Action Buttons */}
                    <div className="flex flex-col sm:flex-row gap-3 pt-2 border-t border-primary">
                        <LemonButton
                            type="primary"
                            icon={<IconPlus />}
                            onClick={() => setShowEventModal(true)}
                            size="small"
                            data-attr="add-revenue-event"
                        >
                            Add Revenue Event
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            icon={<IconPlus />}
                            onClick={() => {
                                setSelectedSource(null)
                                setCurrentView('add-source')
                            }}
                            size="small"
                            data-attr="add-revenue-source"
                        >
                            Connect Revenue Source
                        </LemonButton>
                    </div>
                </div>
            </LemonCard>

            {/* Source Selection */}
            {currentView === 'add-source' && !selectedSource && (
                <LemonCard hoverEffect={false}>
                    <div className="space-y-4">
                        <div className="flex items-center gap-3">
                            <div className="flex items-center justify-center w-12 h-12 rounded-full bg-white border border-primary">
                                <IconDatabase className="w-7 h-7" style={{ color: 'var(--primary-3000)' }} />
                            </div>
                            <div>
                                <h4 className="text-lg font-semibold">Connect Revenue Source</h4>
                                <p className="text-sm text-muted-alt">Choose a revenue platform to import data from</p>
                            </div>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                            {revenueSources.map((source) => (
                                <div
                                    key={source.id}
                                    className={cn(
                                        'relative p-4 rounded-lg border-2',
                                        source.isAvailable
                                            ? source.isConnected
                                                ? 'border-primary bg-primary-lightest'
                                                : 'border-primary bg-bg-light'
                                            : 'border-primary bg-bg-light opacity-60',
                                        source.isAvailable ? 'cursor-pointer' : 'cursor-not-allowed'
                                    )}
                                    onClick={source.isAvailable ? () => handleSourceSelect(source.id) : undefined}
                                >
                                    <div className="flex items-center gap-3 mb-3">
                                        <DataWarehouseSourceIcon type={source.id} size="small" disableTooltip />
                                        <div>
                                            <h5 className="font-medium text-sm">{source.id}</h5>
                                            {!source.isAvailable && (
                                                <span className="text-xs text-warning bg-warning-light p-1 rounded-full">
                                                    Coming Soon
                                                </span>
                                            )}
                                            {source.isConnected && (
                                                <span
                                                    className="text-xs text-white p-1 rounded-full"
                                                    style={{ backgroundColor: 'var(--primary-3000)' }}
                                                >
                                                    Connected
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                    <p className="text-xs text-muted-alt">{source.description}</p>
                                </div>
                            ))}
                        </div>

                        <div className="flex justify-end">
                            <LemonButton type="secondary" onClick={() => setCurrentView('overview')}>
                                Cancel
                            </LemonButton>
                        </div>
                    </div>
                </LemonCard>
            )}

            {/* Source Connection Wizard */}
            {currentView === 'add-source' && selectedSource && (
                <LemonCard hoverEffect={false}>
                    <NewSourcesWizard
                        onComplete={handleFormSuccess}
                        allowedSources={revenueSources.map((source) => source.id)} // Only show revenue-related sources
                        initialSource={selectedSource}
                    />
                </LemonCard>
            )}

            {/* Help Footer */}
            <div className="text-center">
                <p className="text-xs text-muted-alt">
                    Need help? Check our{' '}
                    <Link to="https://posthog.com/docs/revenue-analytics" target="_blank">
                        documentation
                    </Link>
                </p>
            </div>

            {/* Event Configuration Modal */}
            {showEventModal && <EventConfigurationModal onClose={handleEventModalClose} />}
        </div>
    )
}
