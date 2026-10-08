import { useId, useState } from 'react'

import { IconChevronDown, IconChevronRight, IconInfo, IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { HealthFindingActionButton } from './HealthFindingActionButton'
import type { HealthPanelFinding } from './healthPanelFindings'
import { useHealthFindingReporting } from './useHealthFindingReporting'

export function HealthFindingRow({ finding }: { finding: HealthPanelFinding }): JSX.Element {
    const [isDetailOpen, setIsDetailOpen] = useState(false)
    const detailId = useId()
    const { reportOpened, reportActedOn } = useHealthFindingReporting({
        code: finding.code,
        variant: finding.subcode ?? undefined,
    })

    return (
        <div className="flex flex-col gap-1 px-3 py-2" data-attr="experiment-health-finding">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                    {finding.severity === 'info' ? (
                        <IconInfo className="text-secondary text-lg shrink-0" />
                    ) : (
                        <IconWarning
                            className={cn(
                                'text-lg shrink-0',
                                finding.severity === 'critical' ? 'text-danger' : 'text-warning'
                            )}
                        />
                    )}
                    <span className="font-semibold">{finding.title}</span>
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        sideIcon={isDetailOpen ? <IconChevronDown /> : <IconChevronRight />}
                        onClick={() => {
                            if (!isDetailOpen) {
                                reportOpened('why')
                            }
                            setIsDetailOpen(!isDetailOpen)
                        }}
                        aria-expanded={isDetailOpen}
                        aria-controls={detailId}
                        data-attr="experiment-health-finding-why"
                    >
                        Why?
                    </LemonButton>
                </div>
                {finding.actions.length > 0 && (
                    <div className="flex flex-wrap items-center gap-2">
                        {finding.actions.map((actionKind) => (
                            <HealthFindingActionButton
                                key={actionKind}
                                actionKind={actionKind}
                                onClick={() => reportActedOn(actionKind)}
                            />
                        ))}
                    </div>
                )}
            </div>
            {isDetailOpen && (
                <p id={detailId} className="m-0 pl-7 text-secondary">
                    {finding.detail}
                </p>
            )}
        </div>
    )
}
