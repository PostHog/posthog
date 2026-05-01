import './base/LegalDocumentsPreview.scss'

import { useValues } from 'kea'

import { legalDocumentsLogic } from '../scenes/legalDocumentsLogic'
import { BAAPreview } from './documents/baa/BAAPreview'
import { DPAFairytalePreview } from './documents/dpa/DPAFairytalePreview'
import { DPALegalPreview } from './documents/dpa/DPALegalPreview'
import { DPATswiftPreview } from './documents/dpa/DPATswiftPreview'

/**
 * Top-level dispatcher that picks the right agreement template for the current
 * form state. Styles for every template live in `base/LegalDocumentsPreview.scss`
 * and are imported once from here.
 */
export function LegalDocumentsPreview(): JSX.Element {
    const { legalDocument } = useValues(legalDocumentsLogic)

    if (legalDocument.document_type === 'BAA') {
        return <BAAPreview />
    }

    switch (legalDocument.dpa_mode) {
        case 'fairytale':
            return <DPAFairytalePreview />
        case 'tswift':
            return <DPATswiftPreview />
        case 'lawyer':
            return <DPALegalPreview lawyerMode />
        default:
            return <DPALegalPreview />
    }
}
