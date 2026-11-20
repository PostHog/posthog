import { useActions, useValues } from 'kea'

import { codeEmailLogic } from './codeEmailLogic'
import { SourceCandidatePicker } from './SourceCandidatePicker'
import { SourceFileForm } from './SourceFileForm'

export function SourceEditor(): JSX.Element {
    const { codeEmail, saving, sourcePickerOpen } = useValues(codeEmailLogic)
    const { linkSourceFile } = useActions(codeEmailLogic)
    if (sourcePickerOpen) {
        return <SourceCandidatePicker />
    }
    return <SourceFileForm initialUrl={codeEmail?.source_url ?? null} saving={saving} onSave={linkSourceFile} />
}
