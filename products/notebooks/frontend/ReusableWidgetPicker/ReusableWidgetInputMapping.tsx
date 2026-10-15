import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonSelect, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import type { NotebookFrameNodeSummary } from 'scenes/notebooks/Nodes/notebookNodeContent'

import type { WidgetInputContractColumnApi } from '../generated/api.schemas'
import { widgetMappingIssues } from './reusableWidgetMapping'
import { ReusableWidgetPickerLogicProps, reusableWidgetPickerLogic } from './reusableWidgetPickerLogic'

export function ReusableWidgetInputMapping({
    logicProps,
    slot,
    columns,
    frames,
}: {
    logicProps: ReusableWidgetPickerLogicProps
    slot: string
    columns: WidgetInputContractColumnApi[]
    frames: NotebookFrameNodeSummary[]
}): JSX.Element {
    const logic = reusableWidgetPickerLogic(logicProps)
    const { resolvedBindings, attachInFlight, aiHandoffInFlight } = useValues(logic)
    const { setBindingSource, setBindingColumn, setBindingHog, setMappingMode, setAdvancedOpen, matchWithAI } =
        useActions(logic)
    const binding = resolvedBindings[slot]
    const frame = frames.find((frame) => frame.name === binding?.source)
    const issues = frame && columns.length ? widgetMappingIssues(columns, frame) : []
    const customMapping = binding?.mode === 'hog'
    const advanced = customMapping && binding?.advancedOpen

    return (
        <div className="rounded border p-3 flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">{slot}</span>
                <LemonTag size="small">Input</LemonTag>
            </div>
            <div className="flex flex-wrap gap-1">
                {columns.map((column) => (
                    <LemonTag key={column.name} size="small">
                        {column.name}: {column.type}
                    </LemonTag>
                ))}
            </div>
            <div>
                <LemonLabel>Notebook dataframe</LemonLabel>
                <LemonSelect
                    value={binding?.source || undefined}
                    options={frames.map((frame) => ({
                        value: frame.name,
                        label: `${frame.name} (${frame.columns.length} columns)`,
                    }))}
                    onChange={(source) => setBindingSource(slot, source)}
                    placeholder="Choose a dataframe"
                    disabledReason={attachInFlight ? 'Connecting the widget…' : undefined}
                    fullWidth
                />
            </div>
            {frame && !issues.length && !customMapping ? (
                <div className="text-success text-sm">All columns match. Ready to use.</div>
            ) : null}
            {issues.length ? (
                <>
                    <LemonBanner type="warning">
                        <div>This dataframe uses different columns.</div>
                        <ul className="mb-0 pl-4">
                            {issues.map((issue) => (
                                <li key={issue}>{issue}</li>
                            ))}
                        </ul>
                    </LemonBanner>
                    <div className="flex flex-wrap gap-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={matchWithAI}
                            loading={aiHandoffInFlight}
                            disabledReason={attachInFlight ? 'Connecting the widget…' : undefined}
                        >
                            Match with AI
                        </LemonButton>
                        {!customMapping ? (
                            <span className="text-sm text-secondary self-center">
                                Or choose the source columns below.
                            </span>
                        ) : null}
                    </div>
                    {!customMapping
                        ? columns.map((column) => (
                              <div key={column.name}>
                                  <LemonLabel
                                      info={`Choose the column that supplies ${column.name}. The widget expects ${column.type}. For unit conversions or calculations, use AI or advanced mapping.`}
                                  >
                                      {column.name}
                                  </LemonLabel>
                                  <LemonSelect
                                      value={binding?.columns?.[column.name] || undefined}
                                      options={
                                          frame?.columns.map(([name, type]) => ({
                                              value: name,
                                              label: `${name} (${type})`,
                                              disabledReason:
                                                  type !== column.type
                                                      ? 'Use AI or advanced mapping to convert this type.'
                                                      : undefined,
                                          })) ?? []
                                      }
                                      onChange={(source) => setBindingColumn(slot, column.name, source)}
                                      placeholder="Choose a source column"
                                      disabledReason={attachInFlight ? 'Connecting the widget…' : undefined}
                                      fullWidth
                                  />
                              </div>
                          ))
                        : null}
                </>
            ) : null}
            {frame ? (
                <LemonButton
                    type="tertiary"
                    size="small"
                    onClick={() => (customMapping ? setAdvancedOpen(slot, !advanced) : setMappingMode(slot, 'hog'))}
                    disabledReason={attachInFlight ? 'Connecting the widget…' : undefined}
                >
                    {advanced ? 'Hide advanced mapping' : customMapping ? 'Edit custom mapping' : 'Advanced mapping'}
                </LemonButton>
            ) : null}
            {customMapping && !advanced ? (
                <div className="text-sm text-secondary">Custom Hog mapping is active.</div>
            ) : null}
            {advanced ? (
                <div className="flex flex-col gap-2">
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => setMappingMode(slot, 'columns')}
                        disabledReason={attachInFlight ? 'Connecting the widget…' : undefined}
                    >
                        Use column selectors
                    </LemonButton>
                    <LemonLabel info="Hog runs a bounded transformation on each page of data. It cannot call external services. Return a list of objects with the widget’s required column names.">
                        Hog mapping
                    </LemonLabel>
                    <LemonTextArea
                        value={binding?.hog ?? ''}
                        onChange={(hog) => setBindingHog(slot, hog)}
                        minRows={5}
                        className="font-mono ph-no-capture"
                        disabled={attachInFlight}
                    />
                    <div className="text-sm text-secondary">
                        <p>
                            <code>rows</code> is a list of objects, one per row. Access a value with{' '}
                            <code>row['column_name']</code>. <code>columns</code> lists their names and types.{' '}
                            <code>frame</code> also contains pagination metadata.
                        </p>
                        <p className="mb-1">Example: rename a column and convert cents to dollars.</p>
                        <pre className="whitespace-pre-wrap break-words rounded border p-2">
                            {
                                "let mapped := [];\nfor (let row in rows) {\n    mapped := arrayPushBack(mapped, {\n        'revenue': row['amount_cents'] / 100\n    });\n}\nreturn mapped"
                            }
                        </pre>
                        <p className="mb-0">
                            Use <code>return rows</code> to keep the data unchanged. Each page is mapped separately, so
                            use a notebook cell for sorting or totals across all rows.
                        </p>
                    </div>
                </div>
            ) : null}
        </div>
    )
}
