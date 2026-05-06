import { LegalDocumentFieldId } from '../../scenes/legalDocumentsConstants'

interface PlaceholderProps {
    value: string
    fallback: string
    /** If provided, clicking the placeholder focuses the matching input on the form pane. */
    focusTargetId?: LegalDocumentFieldId
}

/** Highlighted placeholder token — shows the user's filled value or a bracketed hint. */
export function Placeholder({ value, fallback, focusTargetId }: PlaceholderProps): JSX.Element {
    const displayValue = value || fallback
    if (!focusTargetId) {
        return (
            <span className="legal-document-preview__placeholder legal-document-preview__placeholder--static">
                {displayValue}
            </span>
        )
    }
    return (
        <button
            type="button"
            className="legal-document-preview__placeholder"
            onClick={() => document.getElementById(focusTargetId)?.focus()}
            title={value ? 'Click to edit on the left' : 'Click to fill this field on the left'}
        >
            {displayValue}
        </button>
    )
}
