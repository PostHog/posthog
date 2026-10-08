import { useValues } from 'kea'

import { LemonTable, LemonTag } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { experimentHealthDebugLogic } from './experimentHealthDebugLogic'
import type { HealthDebugCheck, HealthDebugFact } from './healthDebugReport'

export function HealthDebugTables(): JSX.Element {
    const { experiment, experimentId, healthFindings } = useValues(experimentLogic)
    const { healthDebugChecks: checks, healthDebugFacts: facts } = useValues(
        experimentHealthDebugLogic({ experimentId })
    )

    return (
        <div className="flex flex-col gap-4">
            <LemonTable<HealthDebugFact>
                size="small"
                showHeader={false}
                dataSource={facts}
                rowKey="label"
                columns={[
                    { key: 'label', render: (_, fact) => <span className="font-semibold">{fact.label}</span> },
                    { key: 'value', render: (_, fact) => <span className="font-mono text-xs">{fact.value}</span> },
                ]}
            />
            <LemonTable<HealthDebugCheck>
                size="small"
                dataSource={checks}
                rowKey={(check) => `${check.check}:${check.source}`}
                columns={[
                    { title: 'Check', key: 'check', render: (_, check) => <code>{check.check}</code> },
                    { title: 'Source', dataIndex: 'source' },
                    {
                        title: 'Result',
                        key: 'result',
                        render: (_, check) => (
                            <span className="flex items-center gap-2">
                                <code>{check.result}</code>
                                {check.differs && <LemonTag type="danger">Differs</LemonTag>}
                            </span>
                        ),
                    },
                    { title: 'Inputs', dataIndex: 'note' },
                ]}
            />
            <CodeSnippet language={Language.JSON} thing="health debug data" maxLinesWithoutExpansion={12}>
                {JSON.stringify(
                    { health: experiment.health ?? null, panelFindings: healthFindings, checks, facts },
                    null,
                    2
                )}
            </CodeSnippet>
        </div>
    )
}
