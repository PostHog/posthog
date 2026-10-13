import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import {
    IconCalendar,
    IconFlask,
    IconNotebook,
    IconPencil,
    IconPlus,
    IconSearch,
    IconTrends,
    IconWarning,
} from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard, LemonTag } from '@posthog/lemon-ui'

import { ProjectTimezoneHint } from 'lib/components/ScheduledRunStatus'
import { cn } from 'lib/utils/css-classes'

import { getScoutCreateDisabledReason } from '../../utils/accessControl'
import { replayScannerLogic } from '../replayScannerLogic'
import {
    scannerScoutTemplates,
    variantAnalysisScout,
    type ScannerScoutTemplate,
    type ScannerScoutTemplateKey,
} from '../scannerScout'
import { scannerScoutLogic } from '../scannerScoutLogic'
import { parseScoutCadence, SCOUT_FREQUENCY_OPTIONS } from '../scoutCadence'
import { ScannerScoutFormModal } from './ScannerScoutFormModal'
import { ScannerScoutReportModal } from './ScannerScoutReportModal'
import { ScannerScoutRow } from './ScannerScoutRow'

const TEMPLATE_ICONS: Record<ScannerScoutTemplateKey, JSX.Element> = {
    'variant-analysis': <IconFlask />,
    'daily-digest': <IconCalendar />,
    'root-cause': <IconSearch />,
    'weekly-themes': <IconNotebook />,
    'trend-watch': <IconTrends />,
    'new-issues': <IconWarning />,
    scratch: <IconPencil />,
}

/** Derived from the template's own cron, so a changed schedule can't leave a stale label behind. */
function templateScheduleLabel(template: ScannerScoutTemplate): string {
    const cadence = parseScoutCadence(template.cron)
    const option = cadence && SCOUT_FREQUENCY_OPTIONS.find(({ value }) => value === cadence.frequency)
    return cadence && option ? `${option.shortLabel} at ${cadence.time}` : template.cron
}

function ScoutTemplateCard({
    template,
    disabledReason,
    alreadySetUp,
    onUse,
}: {
    template: ScannerScoutTemplate
    disabledReason?: string
    /** The scanner already has the one scout this template allows, so the card opens it instead. */
    alreadySetUp?: boolean
    onUse: () => void
}): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-2 p-2.5">
            <div className="flex min-w-0 flex-col gap-1">
                <h3 className="m-0 flex items-center gap-1.5 text-sm font-semibold">
                    <span className="shrink-0 text-muted">{TEMPLATE_ICONS[template.key]}</span>
                    {template.title}
                </h3>
                <p className="m-0 text-xs text-muted">{template.description}</p>
            </div>
            {/* Pinned to the bottom so the schedules and buttons line up across a row, whatever each
                description's length. */}
            <div className="mt-auto flex flex-col items-start gap-2">
                {/* The scratch card carries the same default cron, but it isn't a ready-made scout, so
                    advertising a schedule would promise more than it hands you. It keeps the space so its
                    button stays level with the others. */}
                <LemonTag
                    type="muted"
                    size="small"
                    className={template.key === 'scratch' ? 'invisible' : undefined}
                    aria-hidden={template.key === 'scratch'}
                >
                    {alreadySetUp ? (
                        'Already set up'
                    ) : (
                        <>
                            {templateScheduleLabel(template)} <ProjectTimezoneHint />
                        </>
                    )}
                </LemonTag>
                <LemonButton
                    type={alreadySetUp ? 'secondary' : 'primary'}
                    size="xsmall"
                    icon={alreadySetUp ? undefined : <IconPlus />}
                    onClick={onUse}
                    disabledReason={alreadySetUp ? undefined : disabledReason}
                    className="self-end"
                    data-attr={`vision-scout-template-${template.key}`}
                >
                    {/* The scratch card seeds a skeleton rather than a ready-made scout, so
                        "use template" would overpromise what the button hands you. */}
                    {alreadySetUp ? 'Open scout' : template.key === 'scratch' ? 'Create' : 'Use template'}
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
    const { openCreateModal, openScoutSettings, loadScoutConfigs } = useActions(logic)
    const templates = useMemo(
        () => scannerScoutTemplates(scannerId, scanner?.scanner_type, scannerName),
        [scannerId, scanner?.scanner_type, scannerName]
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

    const createDisabledReason = getScoutCreateDisabledReason(scanner?.user_access_level) ?? undefined
    const existingVariantAnalysis = variantAnalysisScout(scoutConfigsForScanner)

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
                {/* Container query: the scene is much narrower than the viewport with a side panel open. */}
                <div className="@container">
                    {/* One row from about 1,000px wide. The cards are sized for it, so a scanner type's
                        four or five templates never leave one card alone on a row. */}
                    <div
                        className={cn(
                            'grid gap-2 @md:grid-cols-2',
                            templates.length > 4 ? '@2xl:grid-cols-5' : '@2xl:grid-cols-4'
                        )}
                    >
                        {templates.map((template) => {
                            const existing = template.key === 'variant-analysis' ? existingVariantAnalysis : undefined
                            return (
                                <ScoutTemplateCard
                                    key={template.key}
                                    template={template}
                                    disabledReason={createDisabledReason}
                                    alreadySetUp={!!existing}
                                    onUse={() =>
                                        existing
                                            ? openScoutSettings(existing.skill_name)
                                            : openCreateModal(template.key)
                                    }
                                />
                            )
                        })}
                    </div>
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
