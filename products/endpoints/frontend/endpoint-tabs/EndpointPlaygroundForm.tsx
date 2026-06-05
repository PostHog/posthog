import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonInput, LemonSegmentedButton, LemonSelect, LemonSwitch, Tooltip } from '@posthog/lemon-ui'

import { superpowersLogic } from 'lib/components/Superpowers/superpowersLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { EndpointRefreshMode, NodeKind } from '~/queries/schema/schema-general'

import { endpointLogic } from '../endpointLogic'
import { endpointSceneLogic } from '../endpointSceneLogic'
import { EndpointPlaygroundVariableRow } from './EndpointPlaygroundVariableRow'

const REFRESH_OPTIONS: { value: EndpointRefreshMode; label: string; tooltip: string }[] = [
    {
        value: 'cache',
        label: 'cache',
        tooltip: 'Return cached results if they are fresh enough; otherwise run the query. Default — fastest.',
    },
    {
        value: 'force',
        label: 'force',
        tooltip: 'Bypass the cache and recompute. For materialized endpoints this still reads the materialized table.',
    },
    {
        value: 'direct',
        label: 'direct',
        tooltip: 'Materialized endpoints only — bypass the materialized table and run the live query against raw data.',
    },
]

function variableErrorFor(name: string, error: string | null): string | null {
    // Server returns: "Required variable(s) '$browser', '$os' not provided"
    // We surface the message under each specific variable input that's named in it.
    if (!error) {
        return null
    }
    const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const regex = new RegExp(`['"]${escaped}['"]`)
    return regex.test(error) ? error : null
}

export function EndpointPlaygroundForm(): JSX.Element {
    const { endpoint } = useValues(endpointLogic)
    const {
        playgroundVariableSpecs,
        playgroundVariableValues,
        playgroundVariableSent,
        playgroundRefresh,
        playgroundLimit,
        playgroundVersion,
        playgroundExecutionError,
        viewingVersion,
        debugMode,
    } = useValues(endpointSceneLogic)
    const {
        setPlaygroundVariableValue,
        setPlaygroundVariableSent,
        setPlaygroundRefresh,
        setPlaygroundLimit,
        setPlaygroundVersion,
        setDebugMode,
    } = useActions(endpointSceneLogic)
    const { superpowersEnabled } = useValues(superpowersLogic)

    if (!endpoint) {
        return <></>
    }

    const isMaterialized = (viewingVersion?.is_materialized ?? endpoint.is_materialized) || false
    const isHogQL = (viewingVersion?.query?.kind ?? endpoint.query?.kind) === NodeKind.HogQLQuery

    const versionOptions = Array.from({ length: endpoint.current_version }, (_, i) => {
        const v = i + 1
        return { value: v, label: v === endpoint.current_version ? `v${v} (current)` : `v${v}` }
    })

    return (
        <div className="flex flex-col gap-4">
            {playgroundVariableSpecs.length > 0 ? (
                <LemonField.Pure
                    label="Variables"
                    info="Unchecked variables are omitted from the request — the response aggregates across every value of that variable."
                >
                    <div className="flex flex-col gap-1.5">
                        {playgroundVariableSpecs.map((spec) => {
                            const variableError = variableErrorFor(spec.name, playgroundExecutionError)
                            return (
                                <EndpointPlaygroundVariableRow
                                    key={spec.name}
                                    spec={spec}
                                    value={playgroundVariableValues[spec.name]}
                                    sent={!!playgroundVariableSent[spec.name]}
                                    errored={!!variableError}
                                    errorMessage={variableError}
                                    onValueChange={(value) => setPlaygroundVariableValue(spec.name, value)}
                                    onSentChange={(sent) => setPlaygroundVariableSent(spec.name, sent)}
                                />
                            )
                        })}
                    </div>
                </LemonField.Pure>
            ) : (
                <p className="text-sm text-secondary m-0">
                    This endpoint has no configurable variables. Use the request options below to control execution.
                </p>
            )}

            <LemonField.Pure
                label="Request options"
                info="Settings applied just to this execution. They don't change the saved endpoint."
            >
                <div className="flex flex-col gap-3">
                    <div className="flex flex-col gap-1">
                        <span className="text-xs text-secondary">Refresh</span>
                        <LemonSegmentedButton
                            value={playgroundRefresh}
                            onChange={(v) => setPlaygroundRefresh(v as EndpointRefreshMode)}
                            options={REFRESH_OPTIONS.map((opt) => ({
                                ...opt,
                                disabledReason:
                                    opt.value === 'direct' && !isMaterialized
                                        ? 'direct is only valid for materialized endpoints'
                                        : undefined,
                            }))}
                            size="small"
                        />
                    </div>
                    {isHogQL && (
                        <div className="flex flex-col gap-1">
                            <span className="text-xs text-secondary inline-flex items-center gap-1">
                                Limit
                                <Tooltip title="Cap on result rows (SQL-based endpoints).">
                                    <IconInfo className="text-sm text-secondary" />
                                </Tooltip>
                            </span>
                            <LemonInput
                                type="number"
                                min={1}
                                value={playgroundLimit ?? undefined}
                                onChange={(v) => setPlaygroundLimit(typeof v === 'number' ? v : null)}
                                placeholder="default"
                                size="small"
                                className="w-32"
                            />
                        </div>
                    )}
                    <div className="flex flex-col gap-1 items-start">
                        <span className="text-xs text-secondary">Version</span>
                        <LemonSelect
                            value={playgroundVersion ?? endpoint.current_version}
                            onChange={(v) => setPlaygroundVersion(v === endpoint.current_version ? null : v)}
                            options={versionOptions}
                            size="small"
                        />
                    </div>
                    {superpowersEnabled && (
                        <div className="flex flex-col gap-1">
                            <span className="text-xs text-secondary">Debug</span>
                            <LemonSwitch
                                checked={debugMode}
                                onChange={setDebugMode}
                                label="Include debug info in response"
                                bordered
                            />
                        </div>
                    )}
                </div>
            </LemonField.Pure>
        </div>
    )
}
