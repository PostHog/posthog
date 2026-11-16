import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'

export type WarehouseNativeQueryEditorProps = {
    label: string
    /** Which columns the query must return. */
    hint: string
    query: string
    onChange: (query: string) => void
    'data-attr'?: string
}

export function WarehouseNativeQueryEditor({
    label,
    hint,
    query,
    onChange,
    'data-attr': dataAttr,
}: WarehouseNativeQueryEditorProps): JSX.Element {
    return (
        <div className="flex flex-col gap-1" data-attr={dataAttr}>
            <LemonLabel>{label}</LemonLabel>
            <CodeEditorResizeable
                language="sql"
                value={query}
                onChange={(value) => onChange(value ?? '')}
                minHeight="8rem"
                maxHeight="24rem"
                options={{
                    minimap: { enabled: false },
                    scrollbar: { alwaysConsumeMouseWheel: false },
                    scrollBeyondLastLine: false,
                    lineNumbers: 'off',
                    folding: false,
                    wordWrap: 'on',
                    renderLineHighlight: 'none',
                }}
            />
            <div className="text-secondary text-xs">{hint}</div>
        </div>
    )
}
