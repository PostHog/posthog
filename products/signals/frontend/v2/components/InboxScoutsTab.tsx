import { useActions, useValues } from 'kea'

import { LemonButton, LemonSwitch, lemonToast } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { DEMO_SCOUTS } from '../mockData'
import { v2InboxLogic } from '../v2InboxLogic'

export function InboxScoutsTab(): JSX.Element {
    const { toggles } = useValues(v2InboxLogic)
    const { toggleSetting } = useActions(v2InboxLogic)

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-3">
                <p className="m-0 flex-1 text-sm text-secondary">
                    Scouts watch your signal sources and open reports when they find something worth acting on.
                </p>
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={() => lemonToast.info('Not part of this demo')}
                    data-attr="v2-new-scout"
                >
                    New scout
                </LemonButton>
            </div>
            <div className="flex flex-col gap-2">
                {DEMO_SCOUTS.map((scout) => {
                    const enabled = toggles[`scout:${scout.id}`]
                    return (
                        <div
                            key={scout.id}
                            className={cn(
                                'flex items-center gap-4 rounded border border-primary bg-surface-primary px-4 py-3',
                                !enabled && 'opacity-70'
                            )}
                        >
                            <div className="flex min-w-0 flex-1 flex-col gap-1">
                                <span className="font-semibold">{scout.name}</span>
                                <span className="text-xs text-secondary">{scout.watches}</span>
                                <span className="font-mono text-[10px] text-tertiary">
                                    {enabled
                                        ? `runs ${scout.cadence} · last run ${scout.lastRun} · ${scout.openReports} open ${
                                              scout.openReports === 1 ? 'report' : 'reports'
                                          }`
                                        : 'paused'}
                                </span>
                            </div>
                            <LemonSwitch
                                checked={enabled}
                                onChange={() => toggleSetting(`scout:${scout.id}`)}
                                data-attr={`v2-scout-toggle-${scout.id}`}
                            />
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
