import React, { useCallback, useMemo, useState } from 'react'

import { CodeEditor, CodeEditorProps } from 'lib/monaco/CodeEditor'

export interface JSONEditorProps {
    onChange?: (val: string | undefined) => void
    lineHeight?: number
    defaultNumberOfLines?: number
    value?: string
    readOnly?: boolean
    maxNumberOfLines?: number
}

export const JSONEditor = React.memo(
    ({
        onChange,
        lineHeight = 20,
        defaultNumberOfLines = 3,
        maxNumberOfLines = 24,
        value = '',
        readOnly = false,
    }: JSONEditorProps): JSX.Element => {
        const valString = value?.toString() || ''
        const defaultLines = Math.max(defaultNumberOfLines, valString.split(/\r\n|\r|\n/).length) + 1
        const defaultHeight = lineHeight * defaultLines
        const [height, setHeight] = useState(defaultHeight)

        const onTextChange = useCallback(
            (val: string | undefined): void => {
                if (val) {
                    const lineCount = val.split(/\r\n|\r|\n/).length
                    const newLineCount = Math.min(Math.max(lineCount, defaultNumberOfLines), maxNumberOfLines) + 1
                    setHeight(lineHeight * newLineCount)
                } else {
                    setHeight(lineHeight * (defaultNumberOfLines + 1))
                }

                if (onChange) {
                    onChange(val)
                }
            },
            [onChange, defaultNumberOfLines, lineHeight, maxNumberOfLines]
        )

        const options = useMemo((): CodeEditorProps['options'] => {
            return {
                readOnly: readOnly,
                lineHeight: lineHeight,
                minimap: {
                    enabled: false,
                },
                scrollbar: {
                    alwaysConsumeMouseWheel: false,
                },
                padding: {
                    bottom: 0,
                    top: 10,
                },
                overviewRulerLanes: 0,
                hideCursorInOverviewRuler: true,
                overviewRulerBorder: false,
                glyphMargin: true,
                folding: false,
                lineNumbers: 'off',
                lineDecorationsWidth: 0,
                lineNumbersMinChars: 0,
                renderLineHighlight: 'none',
                cursorStyle: 'line',
                scrollBeyondLastLine: false,
                quickSuggestions: false,
                contextmenu: false,
            }
        }, [lineHeight, readOnly])

        return (
            <CodeEditor
                className="rounded [&_.monaco-editor]:rounded [&_.monaco-diff-editor]:rounded [&_.overflow-guard]:rounded"
                language="json"
                height={height}
                value={value}
                options={options}
                onChange={onTextChange}
            />
        )
    }
)
JSONEditor.displayName = 'JSONEditor'
