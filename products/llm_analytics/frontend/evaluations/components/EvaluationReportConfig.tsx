import { useActions, useValues } from 'kea'
import { useState } from 'react'

import {
    LemonBadge,
    LemonButton,
    LemonDialog,
    LemonDivider,
    LemonInput,
    LemonSelect,
    LemonSwitch,
    LemonTable,
} from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SlackChannelPicker, SlackNotConfiguredBanner } from 'lib/integrations/SlackIntegrationHelpers'

import { evaluationReportLogic } from '../evaluationReportLogic'
import type { EvaluationReportDeliveryTarget, EvaluationReportFrequency, EvaluationReportRun } from '../types'
import { EvaluationReportViewer } from './EvaluationReportViewer'

const FREQUENCY_OPTIONS = [
    { value: 'hourly' as const, label: 'Hourly' },
    { value: 'daily' as const, label: 'Daily' },
    { value: 'weekly' as const, label: 'Weekly' },
]

/** Shared delivery targets configuration */
function DeliveryTargetsConfig({
    emailValue,
    onEmailChange,
    slackIntegrationId,
    onSlackIntegrationChange,
    slackChannelValue,
    onSlackChannelChange,
}: {
    emailValue: string
    onEmailChange: (value: string) => void
    slackIntegrationId: number | null
    onSlackIntegrationChange: (value: number | null) => void
    slackChannelValue: string
    onSlackChannelChange: (value: string) => void
}): JSX.Element {
    const { slackIntegrations, integrations } = useValues(integrationsLogic)

    return (
        <>
            <div>
                <label className="font-semibold text-sm">Email recipients</label>
                <LemonInput
                    value={emailValue}
                    onChange={onEmailChange}
                    placeholder="email1@example.com, email2@example.com"
                    fullWidth
                />
                <p className="text-xs text-muted mt-1">Comma-separated email addresses</p>
            </div>
            <div>
                <label className="font-semibold text-sm">Slack channel</label>
                {!slackIntegrations?.length ? (
                    <SlackNotConfiguredBanner />
                ) : (
                    <div className="space-y-2">
                        <IntegrationChoice
                            integration="slack"
                            value={slackIntegrationId ?? undefined}
                            onChange={(newValue) => {
                                if (newValue !== slackIntegrationId) {
                                    onSlackChannelChange('')
                                }
                                onSlackIntegrationChange(newValue)
                            }}
                        />
                        {slackIntegrationId && (
                            <SlackChannelPicker
                                value={slackChannelValue}
                                onChange={(val) => onSlackChannelChange(val || '')}
                                integration={integrations!.find((i) => i.id === slackIntegrationId)!}
                            />
                        )}
                    </div>
                )}
            </div>
        </>
    )
}

/** Inline config shown during new evaluation creation */
function PendingReportConfig({ evaluationId }: { evaluationId: string }): JSX.Element {
    const { pendingConfig } = useValues(evaluationReportLogic({ evaluationId }))
    const {
        setPendingEnabled,
        setPendingFrequency,
        setPendingEmailValue,
        setPendingSlackIntegrationId,
        setPendingSlackChannelValue,
    } = useActions(evaluationReportLogic({ evaluationId }))

    return (
        <div className="bg-bg-light border rounded p-6">
            <div className="flex items-center justify-between mb-4">
                <div>
                    <h3 className="text-lg font-semibold mb-1">Scheduled reports</h3>
                    <p className="text-muted text-sm">
                        Get periodic AI-generated analysis of evaluation results delivered via email or Slack.
                    </p>
                </div>
                <LemonSwitch
                    checked={pendingConfig.enabled}
                    onChange={setPendingEnabled}
                    bordered
                    label={pendingConfig.enabled ? 'Enabled' : 'Disabled'}
                />
            </div>

            {pendingConfig.enabled && (
                <div className="space-y-4 mt-4">
                    <div>
                        <label className="font-semibold text-sm">Frequency</label>
                        <LemonSelect
                            value={pendingConfig.frequency}
                            onChange={(val) => val && setPendingFrequency(val)}
                            options={FREQUENCY_OPTIONS}
                            fullWidth
                        />
                    </div>
                    <DeliveryTargetsConfig
                        emailValue={pendingConfig.emailValue}
                        onEmailChange={setPendingEmailValue}
                        slackIntegrationId={pendingConfig.slackIntegrationId}
                        onSlackIntegrationChange={setPendingSlackIntegrationId}
                        slackChannelValue={pendingConfig.slackChannelValue}
                        onSlackChannelChange={setPendingSlackChannelValue}
                    />
                </div>
            )}
        </div>
    )
}

/** Toggle-based report management for existing evaluations */
function ExistingReportConfig({ evaluationId }: { evaluationId: string }): JSX.Element {
    const logic = evaluationReportLogic({ evaluationId })
    const { reportRuns, reportRunsLoading, selectedReportRun, activeReport, reportsLoading } = useValues(logic)
    const { updateReport, deleteReport, loadReportRuns, generateReport, selectReportRun, createReport } =
        useActions(logic)

    // Local state: toggle controls form visibility, Save button creates the report
    const [formEnabled, setFormEnabled] = useState(false)
    const [frequency, setFrequency] = useState<EvaluationReportFrequency>('daily')
    const [emailValue, setEmailValue] = useState('')
    const [slackIntegrationId, setSlackIntegrationId] = useState<number | null>(null)
    const [slackChannelValue, setSlackChannelValue] = useState('')

    if (selectedReportRun) {
        return <EvaluationReportViewer reportRun={selectedReportRun} onClose={() => selectReportRun(null)} />
    }

    const isEnabled = !!activeReport || formEnabled

    const handleToggle = (checked: boolean): void => {
        if (checked) {
            setFormEnabled(true)
        } else if (activeReport) {
            LemonDialog.open({
                title: 'Disable scheduled reports?',
                description: 'This will stop all future report deliveries. Past reports will be preserved.',
                primaryButton: {
                    children: 'Disable',
                    status: 'danger',
                    onClick: () => deleteReport(activeReport.id),
                },
                secondaryButton: { children: 'Cancel' },
            })
        } else {
            setFormEnabled(false)
        }
    }

    const hasEmail = emailValue.trim().length > 0
    const hasSlack = slackIntegrationId !== null && slackChannelValue.length > 0

    const handleSave = (): void => {
        const targets: EvaluationReportDeliveryTarget[] = []
        if (hasEmail) {
            targets.push({ type: 'email', value: emailValue.trim() })
        }
        if (hasSlack) {
            targets.push({ type: 'slack', integration_id: slackIntegrationId!, channel: slackChannelValue })
        }
        createReport({ evaluationId, frequency, delivery_targets: targets })
        setFormEnabled(false)
    }

    return (
        <div className="bg-bg-light border rounded p-6">
            <div className="flex items-center justify-between mb-4">
                <div>
                    <h3 className="text-lg font-semibold mb-1">Scheduled reports</h3>
                    <p className="text-muted text-sm">
                        Get periodic AI-generated analysis of evaluation results delivered via email or Slack.
                    </p>
                </div>
                <LemonSwitch
                    checked={isEnabled}
                    onChange={handleToggle}
                    bordered
                    loading={reportsLoading}
                    label={isEnabled ? 'Enabled' : 'Disabled'}
                />
            </div>

            {activeReport ? (
                <div className="space-y-4 mt-4">
                    <div>
                        <label className="font-semibold text-sm">Frequency</label>
                        <LemonSelect
                            value={activeReport.frequency}
                            onChange={(val) =>
                                val && updateReport({ reportId: activeReport.id, data: { frequency: val } })
                            }
                            options={FREQUENCY_OPTIONS}
                            fullWidth
                        />
                    </div>

                    <div className="text-sm text-muted">
                        Delivering to:{' '}
                        {activeReport.delivery_targets.map((t: EvaluationReportDeliveryTarget, i: number) => (
                            <span key={i}>
                                {t.type === 'email' ? t.value : `Slack: ${t.channel}`}
                                {i < activeReport.delivery_targets.length - 1 ? ', ' : ''}
                            </span>
                        ))}
                    </div>

                    {activeReport.next_delivery_date && (
                        <div className="text-sm text-muted">
                            Next delivery: {new Date(activeReport.next_delivery_date).toLocaleString()}
                        </div>
                    )}

                    <div className="flex items-center gap-2">
                        <LemonButton size="small" type="secondary" onClick={() => generateReport(activeReport.id)}>
                            Generate now
                        </LemonButton>
                    </div>

                    {/* Report history */}
                    <LemonDivider className="my-1" />
                    <div className="flex items-center justify-between">
                        <h4 className="font-semibold text-sm mb-0">Report history</h4>
                        <LemonButton
                            size="xsmall"
                            onClick={() => loadReportRuns(activeReport.id)}
                            loading={reportRunsLoading}
                        >
                            Load history
                        </LemonButton>
                    </div>

                    <LemonTable
                        dataSource={reportRuns}
                        loading={reportRunsLoading}
                        columns={[
                            {
                                title: 'Period',
                                render: (_, run: EvaluationReportRun) =>
                                    `${new Date(run.period_start).toLocaleDateString()} – ${new Date(run.period_end).toLocaleDateString()}`,
                            },
                            {
                                title: 'Status',
                                render: (_, run: EvaluationReportRun) => (
                                    <LemonBadge
                                        content={run.delivery_status}
                                        status={
                                            run.delivery_status === 'delivered'
                                                ? 'success'
                                                : run.delivery_status === 'failed'
                                                  ? 'danger'
                                                  : 'muted'
                                        }
                                    />
                                ),
                            },
                            {
                                title: 'Created',
                                render: (_, run: EvaluationReportRun) => new Date(run.created_at).toLocaleString(),
                            },
                            {
                                title: '',
                                render: (_, run: EvaluationReportRun) => (
                                    <LemonButton size="xsmall" onClick={() => selectReportRun(run)}>
                                        View
                                    </LemonButton>
                                ),
                            },
                        ]}
                        emptyState="No reports generated yet"
                        size="small"
                    />
                </div>
            ) : (
                formEnabled && (
                    <div className="space-y-4 mt-4">
                        <div>
                            <label className="font-semibold text-sm">Frequency</label>
                            <LemonSelect
                                value={frequency}
                                onChange={(val) => val && setFrequency(val)}
                                options={FREQUENCY_OPTIONS}
                                fullWidth
                            />
                        </div>
                        <DeliveryTargetsConfig
                            emailValue={emailValue}
                            onEmailChange={setEmailValue}
                            slackIntegrationId={slackIntegrationId}
                            onSlackIntegrationChange={setSlackIntegrationId}
                            slackChannelValue={slackChannelValue}
                            onSlackChannelChange={setSlackChannelValue}
                        />
                        <div className="flex justify-end">
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={handleSave}
                                loading={reportsLoading}
                                disabledReason={!hasEmail && !hasSlack ? 'Add at least one delivery target' : undefined}
                            >
                                Save report schedule
                            </LemonButton>
                        </div>
                    </div>
                )
            )}
        </div>
    )
}

export function EvaluationReportConfig({ evaluationId }: { evaluationId: string }): JSX.Element {
    if (evaluationId === 'new') {
        return <PendingReportConfig evaluationId={evaluationId} />
    }
    return <ExistingReportConfig evaluationId={evaluationId} />
}
