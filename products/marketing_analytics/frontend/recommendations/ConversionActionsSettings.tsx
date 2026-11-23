import { ConversionActionsEditor } from './ConversionActionsEditor'

export function ConversionActionsSettings(): JSX.Element {
    return (
        <div className="flex flex-col gap-2" data-attr="marketing-recommendations-conversion-actions-settings">
            <h3 className="mb-0 text-lg font-semibold">Recommendation conversion actions</h3>
            <ConversionActionsEditor />
        </div>
    )
}
