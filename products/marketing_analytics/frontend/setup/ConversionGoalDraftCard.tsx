import { LemonBanner, LemonButton, LemonCard, LemonCheckbox, LemonInput, LemonTag } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { ConversionGoalDropdown } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/common/ConversionGoalDropdown'

import type { ConversionGoalFilter } from '~/queries/schema/schema-general'

import type {
    ConversionGoalApi,
    ConversionGoalPreviewApi,
    ConversionGoalPreviewResponseApi,
} from '../generated/api.schemas'

export interface ConversionGoalDraftCardProps {
    draft: ConversionGoalPreviewApi
    preview: ConversionGoalPreviewResponseApi | null
    busy: 'preview' | 'save' | 'verify' | null
    error: string | null
    confirmed: boolean
    saveStatus: 'idle' | 'unknown' | 'saved'
    saveDisabledReason?: string
    restrictionReason?: string | null
    onChange: (goal: ConversionGoalApi) => void
    onConfirm: (confirmed: boolean) => void
    onPreview: () => void
    onSave: () => void
    onVerify: () => void
}

export function ConversionGoalDraftCard({
    draft,
    preview,
    busy,
    error,
    confirmed,
    saveStatus,
    saveDisabledReason,
    restrictionReason,
    onChange,
    onConfirm,
    onPreview,
    onSave,
    onVerify,
}: ConversionGoalDraftCardProps): JSX.Element {
    const editingDisabled = busy
        ? 'Wait for the current request to finish.'
        : saveStatus !== 'idle'
          ? 'Check the saved goal before editing.'
          : undefined
    return (
        <LemonCard className="space-y-4" data-attr="marketing-conversion-draft">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="mb-0">Review conversion goal</h3>
                <LemonTag type={saveStatus === 'saved' ? 'success' : 'default'}>
                    {saveStatus === 'saved'
                        ? 'Saved and verified'
                        : saveStatus === 'unknown'
                          ? 'Save needs verification'
                          : preview
                            ? 'Preview complete'
                            : 'Preview needed'}
                </LemonTag>
            </div>
            <LemonField.Pure label="Goal name">
                <LemonInput
                    value={draft.goal.conversion_goal_name}
                    onChange={(name) => onChange({ ...draft.goal, conversion_goal_name: name })}
                    disabledReason={editingDisabled}
                />
            </LemonField.Pure>
            <fieldset disabled={!!editingDisabled} className="min-w-0 border-0 p-0 m-0">
                <ConversionGoalDropdown
                    value={draft.goal as ConversionGoalFilter}
                    onChange={(goal) => {
                        if (!editingDisabled) {
                            onChange(goal as ConversionGoalApi)
                        }
                    }}
                    typeKey="marketing-ai-conversion-draft"
                    disabledReason={editingDisabled}
                />
            </fieldset>
            {draft.goal.math === 'sum' && (
                <p className="mb-0 text-secondary text-sm break-words">
                    Amount currency:{' '}
                    {draft.goal.math_property_revenue_currency?.static ||
                        (draft.goal.math_property_revenue_currency?.property
                            ? `from ${draft.goal.math_property_revenue_currency.property}`
                            : 'project default')}
                    . Amounts must be in currency units.
                </p>
            )}
            <div className="flex flex-wrap gap-4">
                <LemonCheckbox
                    label="Revenue"
                    checked={!!draft.goal.counts_as_revenue}
                    onChange={(value) => onChange({ ...draft.goal, counts_as_revenue: value })}
                    disabledReason={editingDisabled}
                />
                <LemonCheckbox
                    label="Customer"
                    checked={!!draft.goal.counts_as_customer}
                    onChange={(value) => onChange({ ...draft.goal, counts_as_customer: value })}
                    disabledReason={editingDisabled}
                />
            </div>
            {error && <LemonBanner type="error">{error}</LemonBanner>}
            {preview && (
                <>
                    <p className="text-secondary text-xs mb-0 break-words">
                        <span>{`${preview.date_from} to ${preview.date_to} (${preview.timezone}). ${preview.attribution_window_days}-day attribution window. Test accounts ${preview.filter_test_accounts ? 'excluded' : 'included'}. Repeat conversions ${preview.allows_multiple_conversions_per_visitor ? 'included' : 'excluded'}.`}</span>
                    </p>
                    <dl className="grid grid-cols-2 gap-3 mb-0">
                        <div>
                            <dt>Conversions</dt>
                            <dd>{preview.total_conversions.toLocaleString()}</dd>
                        </div>
                        <div>
                            <dt>Value</dt>
                            <dd>
                                {preview.total_value === null
                                    ? 'Unavailable'
                                    : `${preview.total_value.toLocaleString()} ${preview.currency ?? ''}`}
                            </dd>
                        </div>
                        <div>
                            <dt>Attributed conversions</dt>
                            <dd>{preview.attributed_conversions.toLocaleString()}</dd>
                        </div>
                        <div>
                            <dt>Unattributed conversions</dt>
                            <dd>{preview.unattributed_conversions.toLocaleString()}</dd>
                        </div>
                    </dl>
                    <p className="text-secondary text-xs mb-0">
                        This preview uses journey attribution. Dashboard filters can differ. It does not validate the
                        business definition.
                    </p>
                    {(preview.exclude_direct_traffic || preview.exclude_unattributed) && (
                        <p className="text-secondary text-xs mb-0">
                            {preview.exclude_direct_traffic && 'Direct traffic is excluded. '}
                            {preview.exclude_unattributed && 'Unattributed conversions are excluded.'}
                        </p>
                    )}
                    {preview.is_approximate && (
                        <LemonBanner type="warning">
                            Evaluation limits or invalid values affect this preview. Review its warnings before saving.
                        </LemonBanner>
                    )}
                    {preview.warnings.length > 0 && (
                        <ul className="mb-0 pl-5 text-sm">
                            {preview.warnings.map((warning) => (
                                <li key={warning}>{warning}</li>
                            ))}
                        </ul>
                    )}
                    {preview.checks_not_performed.length > 0 && (
                        <details>
                            <summary>Checks not performed</summary>
                            <ul className="pl-5">
                                {preview.checks_not_performed.map((check) => (
                                    <li key={check}>{check.replaceAll('_', ' ')}</li>
                                ))}
                            </ul>
                        </details>
                    )}
                    {saveStatus === 'idle' && (
                        <LemonCheckbox
                            label="I confirmed the business definition, counting entity, and source checks relevant to this goal."
                            checked={confirmed}
                            onChange={onConfirm}
                            disabledReason={editingDisabled}
                        />
                    )}
                </>
            )}
            <div className="flex flex-wrap gap-2">
                {saveStatus === 'idle' && (
                    <>
                        <LemonButton
                            type="secondary"
                            loading={busy === 'preview'}
                            disabledReason={editingDisabled}
                            onClick={onPreview}
                            data-attr="marketing-conversion-preview"
                        >
                            Preview draft
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            loading={busy === 'save' || busy === 'verify'}
                            disabledReason={restrictionReason || saveDisabledReason}
                            onClick={onSave}
                            data-attr="marketing-conversion-save"
                        >
                            Save conversion goal
                        </LemonButton>
                    </>
                )}
                {saveStatus === 'unknown' && (
                    <LemonButton
                        type="secondary"
                        loading={busy === 'verify'}
                        disabled={!!busy}
                        onClick={onVerify}
                        data-attr="marketing-conversion-verify"
                    >
                        Retry and verify save
                    </LemonButton>
                )}
            </div>
        </LemonCard>
    )
}
