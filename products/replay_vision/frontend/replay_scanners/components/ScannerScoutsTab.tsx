import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconCalendar, IconPencil, IconPlus, IconTrends, IconWarning } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard, LemonTag } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { replayScannerLogic } from '../replayScannerLogic'
import { scannerScoutTemplates, type ScannerScoutTemplate, type ScannerScoutTemplateKey } from '../scannerScout'
import { scannerScoutLogic } from '../scannerScoutLogic'
import { parseScoutCadence, SCOUT_FREQUENCY_OPTIONS } from '../scoutCadence'
import { ScannerScoutFormModal } from './ScannerScoutFormModal'
import { ScannerScoutReportModal } from './ScannerScoutReportModal'
import { ScannerScoutRow } from './ScannerScoutRow'

const TEMPLATE_ICONS: Record<ScannerScoutTemplateKey, JSX.Element> = {
    'daily-digest': <IconCalendar />,
    'trend-watch': <IconTrends />,
    'new-issues': <IconWarning />,
    scratch: <IconPencil />,
}

/** Derived from the template's own cron, so a changed schedule can't leave a stale label behind. */
function templateScheduleLabel(template: ScannerScoutTemplate): string {
    const cadence = parseScoutCadence(template.cron)
    if (!cadence) {
        return template.cron
    }
    const frequency = SCOUT_FREQUENCY_OPTIONS.find((option) => option.value === cadence.frequency)
    return `${frequency?.label ?? 'Every day'} at ${cadence.time}`
}

function ScoutTemplateCard({
    template,
    disabledReason,
    onUse,
}: {
    template: ScannerScoutTemplate
    disabledReason?: string
    onUse: () => void
}): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-3 p-3">
            <div className="flex min-w-0 items-start gap-2">
                <span className="mt-0.5 shrink-0 text-muted">{TEMPLATE_ICONS[template.key]}</span>
                <div className="min-w-0">
                    <h3 className="m-0 text-sm font-semibold">{template.title}</h3>
                    <p className="m-0 text-xs text-muted">{template.description}</p>
                </div>
            </div>
            <div className="mt-auto flex items-center justify-between gap-2">
                {/* The scratch card carries the same default cron, but it isn't a ready-made scout,
                    so advertising a schedule would promise more than it hands you. */}
                {template.key === 'scratch' ? (
                    <span />
                ) : (
                    <LemonTag type="muted" size="small">
                        {templateScheduleLabel(template)}
                    </LemonTag>
                )}
                <LemonButton
                    type="primary"
                    size="small"
                    icon={<IconPlus />}
                    onClick={onUse}
                    disabledReason={disabledReason}
                    data-attr={`vision-scout-template-${template.key}`}
                >
                    {/* The scratch card seeds a skeleton rather than a ready-made scout, so
                        "use template" would overpromise what the button hands you. */}
                    {template.key === 'scratch' ? 'Create' : 'Use template'}
                </LemonButton>
            </div>
        </LemonCard>
    )
}

/** The scanner's scouts: scheduled agents that read its new observations and file a report to the
 * inbox when something is worth reporting. Templates to start from, then the scanner's own roster. */
export function ScannerScoutsTab({ scannerId }: { scannerId: string }): JSX.Element | null {
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))
    const scannerName = scanner?.name || ''
    const logic = scannerScoutLogic({ scannerId, scannerName })
    const {
        scoutConfigs,
        scoutConfigsLoading,
        scoutConfigsForScanner,
        createTemplateKey,
        settingsSkillName,
        enrolled,
        scoutConfigsFailed,
    } = useValues(logic)
    const { openCreateModal, loadScoutConfigs } = useActions(logic)
    const templates = useMemo(
        () => scannerScoutTemplates(scannerId, scanner?.scanner_type),
        [scannerId, scanner?.scanner_type]
    )

    if (scoutConfigs === null && scoutConfigsLoading) {
        return null
    }

    if (scoutConfigs === null && scoutConfigsFailed) {
        return (
            <LemonBanner
                type="error"
                action={{ children: 'Try again', onClick: () => loadScoutConfigs() }}
                className="text-sm"
            >
                Couldn't load this scanner's scouts.
            </LemonBanner>
        )
    }

    // A scout reads this scanner's observations on a schedule, so creating one needs edit access to
    // the scanner as well as to skills, the same bar the digest and alert flows apply.
    const createDisabledReason =
        getReplayVisionEditDisabledReason(scanner?.user_access_level) ??
        getAccessControlDisabledReason(AccessControlResourceType.LlmSkill, AccessControlLevel.Editor) ??
        undefined

    return (
        <div className="flex flex-col gap-6">
            {enrolled === false && (
                <LemonBanner type="warning" className="text-sm">
                    Scouts aren't enabled for this project yet, so any scout you set up here won't run on its schedule.
                </LemonBanner>
            )}

            <section className="flex flex-col gap-2">
                <div>
                    <h2 className="m-0 text-base font-semibold">Create a scout</h2>
                    <p className="m-0 text-sm text-muted">
                        A scout is a scheduled agent that reads this scanner's new observations and writes up anything
                        worth a look. Pick a starting point, then review and edit it before saving.
                    </p>
                </div>
                <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
                    {templates.map((template) => (
                        <ScoutTemplateCard
                            key={template.key}
                            template={template}
                            disabledReason={createDisabledReason}
                            onUse={() => openCreateModal(template.key)}
                        />
                    ))}
                </div>
            </section>

            <section className="flex flex-col gap-2">
                <div>
                    <h2 className="m-0 text-base font-semibold">This scanner's scouts</h2>
                    <p className="m-0 text-sm text-muted">Their latest findings show on the Overview tab.</p>
                </div>
                {scoutConfigsForScanner.length === 0 ? (
                    <LemonCard hoverEffect={false} className="p-4 text-sm text-muted">
                        No scouts on this scanner yet. Use a template above to add one.
                    </LemonCard>
                ) : (
                    <div className="flex flex-col gap-2">
                        {scoutConfigsForScanner.map((config) => (
                            <ScannerScoutRow
                                key={config.id}
                                scannerId={scannerId}
                                scannerName={scannerName}
                                config={config}
                            />
                        ))}
                    </div>
                )}
            </section>

            <ScannerScoutFormModal
                key={createTemplateKey ?? settingsSkillName ?? 'closed'}
                scannerId={scannerId}
                scannerName={scannerName}
            />
            <ScannerScoutReportModal scannerId={scannerId} scannerName={scannerName} />
        </div>
    )
}
