import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { LemonButton, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Popover } from 'lib/lemon-ui/Popover/Popover'

import { FunnelsQuery, NodeKind } from '~/queries/schema/schema-general'
import type { FeatureFlagType } from '~/types'

import {
    isV1FeatureFlagConfig,
    isRulesV2FeatureFlagConfig,
} from 'products/feature_flags/frontend/featureFlagConfigFormat'

import { notebookFunnel } from './launchReview'
import { appCellTitle } from './notebookAppLayout'
import { notebookAppLogic } from './notebookAppLogic'

function flagValues(config: FeatureFlagType['filters']): string[] {
    if (isV1FeatureFlagConfig(config)) {
        const variants = config.multivariate?.variants?.map(({ key }) => key)
        return variants?.length ? [...variants, 'false'] : ['true', 'false']
    }
    return isRulesV2FeatureFlagConfig(config) && config.return_type === 'boolean' ? ['true', 'false'] : []
}

function eventFunnel(entry: string, adoption: string): FunnelsQuery | undefined {
    if (!entry || !adoption) {
        return undefined
    }
    return {
        kind: NodeKind.FunnelsQuery,
        dateRange: { date_from: '-30d' },
        series: [entry, adoption].map((event) => ({ kind: NodeKind.EventsNode, event })),
    }
}

export function NotebookLaunchReviewStarter({ shortId }: { shortId: string }): JSX.Element {
    const logic = notebookAppLogic({ shortId })
    const { cells, savedNotebookLoading } = useValues(logic)
    const [open, setOpen] = useState(false)
    const [picker, setPicker] = useState<'flag' | 'entry' | 'adoption' | null>(null)
    const [flag, setFlag] = useState<{ id: number; key: string; values: string[] } | null>(null)
    const [flagValue, setFlagValue] = useState('')
    const [entry, setEntry] = useState('')
    const [adoption, setAdoption] = useState('')
    const [funnelId, setFunnelId] = useState('')
    const existing = cells.flatMap((cell) => {
        const source = notebookFunnel(cell)
        return source ? [{ value: cell.id, label: appCellTitle(cell), source }] : []
    })
    const selectedFunnel = existing.find(({ value }) => value === funnelId)?.source
    const funnel = selectedFunnel ?? eventFunnel(entry, adoption)
    function field(kind: 'flag' | 'entry' | 'adoption', label: string, value: string): JSX.Element {
        const groupType = kind === 'flag' ? TaxonomicFilterGroupType.FeatureFlags : TaxonomicFilterGroupType.Events
        return (
            <div className="flex flex-col gap-1">
                <span className="font-medium">{label}</span>
                <Popover
                    visible={picker === kind}
                    placement="bottom-start"
                    onClickOutside={() => setPicker(null)}
                    overlay={
                        <TaxonomicFilter
                            taxonomicGroupTypes={[groupType]}
                            groupType={groupType}
                            onChange={(_, value, item: FeatureFlagType) => {
                                if (kind === 'flag') {
                                    if (!item?.key || !Number(value)) {
                                        return
                                    }
                                    const values = item.filters ? flagValues(item.filters) : []
                                    setFlag({ id: Number(value), key: item.key, values })
                                    setFlagValue(values[0] ?? '')
                                } else if (typeof value === 'string') {
                                    if (kind === 'entry') {
                                        setEntry(value)
                                    } else {
                                        setAdoption(value)
                                    }
                                }
                                setPicker(null)
                            }}
                        />
                    }
                >
                    <LemonButton
                        type="secondary"
                        aria-label={label}
                        data-attr={'notebook-launch-review-' + kind}
                        onClick={() => setPicker(picker === kind ? null : kind)}
                    >
                        {value || (kind === 'flag' ? 'Choose a feature flag' : 'Choose an event')}
                    </LemonButton>
                </Popover>
            </div>
        )
    }

    return (
        <>
            <LemonButton
                size="small"
                type="secondary"
                fullWidth
                data-attr="notebook-launch-review-start"
                onClick={() => {
                    setOpen(true)
                    posthog.capture('notebook app launch review started', { short_id: shortId })
                }}
            >
                Feature launch review
            </LemonButton>
            <LemonModal
                title="Feature launch review"
                isOpen={open}
                onClose={() => {
                    setOpen(false)
                    setPicker(null)
                }}
                footer={
                    <>
                        <LemonButton type="secondary" onClick={() => setOpen(false)}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            data-attr="notebook-launch-review-create"
                            loading={savedNotebookLoading}
                            disabledReason={
                                !flag || !flagValue.trim() || !funnel
                                    ? 'Choose a flag, its value, and both funnel steps.'
                                    : undefined
                            }
                            onClick={() => {
                                if (flag && funnel) {
                                    logic.actions.createLaunchReview({
                                        flagId: flag.id,
                                        flagKey: flag.key,
                                        flagValue: flagValue.trim(),
                                        funnel,
                                    })
                                    setOpen(false)
                                    setPicker(null)
                                }
                            }}
                        >
                            Create draft
                        </LemonButton>
                    </>
                }
            >
                <div className="flex flex-col gap-4">
                    <p className="m-0">
                        Build an adoption funnel for people who entered with the selected flag value, then watch their
                        recordings.
                    </p>
                    {field('flag', 'Feature flag', flag?.key ?? '')}
                    {flag && (
                        <label className="flex flex-col gap-1 font-medium">
                            Flag value
                            {flag.values.length ? (
                                <LemonSelect
                                    aria-label="Flag value"
                                    value={flagValue}
                                    onChange={setFlagValue}
                                    options={flag.values.map((value) => ({ value, label: value }))}
                                />
                            ) : (
                                <LemonInput
                                    value={flagValue}
                                    onChange={setFlagValue}
                                    placeholder="Enter the value captured on the event"
                                    maxLength={200}
                                />
                            )}
                        </label>
                    )}
                    {existing.length > 0 && (
                        <label className="flex flex-col gap-1 font-medium">
                            Funnel
                            <LemonSelect
                                value={funnelId}
                                onChange={setFunnelId}
                                options={[{ value: '', label: 'Choose event steps' }, ...existing]}
                            />
                        </label>
                    )}
                    {!selectedFunnel && (
                        <>
                            {field('entry', 'Entry event', entry)}
                            {field('adoption', 'Adoption event', adoption)}
                        </>
                    )}
                </div>
            </LemonModal>
        </>
    )
}
