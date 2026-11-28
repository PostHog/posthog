import { useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner, LemonButton, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'

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

export function NotebookLaunchReviewForm({
    shortId,
    emptyApp,
    saving,
    onClose,
}: {
    shortId: string
    emptyApp: boolean
    saving: boolean
    onClose: () => void
}): JSX.Element {
    const logic = notebookAppLogic({ shortId })
    const { cells } = useValues(logic)
    const [saveError, setSaveError] = useState<string | null>(null)
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
            <LemonModal.Content>
                <fieldset disabled={saving} className="m-0 flex flex-col gap-4 border-0 p-0">
                    <p className="m-0">
                        {emptyApp
                            ? 'Save the flag, adoption funnel, and recordings to your draft and their source cells to the notebook.'
                            : 'Add a Launch review tab and save the whole draft, including your current edits. Source cells are saved to the notebook.'}
                    </p>
                    {saveError && <LemonBanner type="error">{saveError}</LemonBanner>}
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
                </fieldset>
            </LemonModal.Content>
            <LemonModal.Footer>
                <LemonButton
                    type="secondary"
                    onClick={onClose}
                    disabledReason={saving ? 'Saving your draft.' : undefined}
                >
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    data-attr="notebook-launch-review-create"
                    loading={saving}
                    disabledReason={
                        !flag || !flagValue.trim() || !funnel ? 'Choose a flag, its value, and a funnel.' : undefined
                    }
                    onClick={async () => {
                        if (flag && funnel) {
                            setSaveError(null)
                            await logic.asyncActions.createLaunchReview({
                                flagId: flag.id,
                                flagKey: flag.key,
                                flagValue: flagValue.trim(),
                                funnel,
                            })
                            if (logic.values.error) {
                                setSaveError(logic.values.error)
                            } else {
                                onClose()
                            }
                        }
                    }}
                >
                    Save to draft
                </LemonButton>
            </LemonModal.Footer>
        </>
    )
}
