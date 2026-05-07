import { useValues } from 'kea'

import { dayjs } from 'lib/dayjs'

import { FIELD_IDS } from '../../scenes/legalDocumentsConstants'
import { legalDocumentsLogic } from '../../scenes/legalDocumentsLogic'
import { Placeholder } from './Placeholder'

function ordinalSuffix(day: number): string {
    const v = day % 100
    if (v >= 11 && v <= 13) {
        return 'th'
    }
    switch (day % 10) {
        case 1:
            return 'st'
        case 2:
            return 'nd'
        case 3:
            return 'rd'
        default:
            return 'th'
    }
}

export function SignatureBlock(): JSX.Element {
    const { legalDocument } = useValues(legalDocumentsLogic)
    const now = dayjs()
    const day = now.date()
    const today = `${now.format('MMMM')} ${day}${ordinalSuffix(day)}`

    return (
        <div className="mt-8 space-y-6">
            <div>
                <div className="font-semibold mb-2">Customer</div>
                <div className="grid grid-cols-[minmax(100px,200px)_1fr] items-baseline gap-y-3">
                    <span>Signature</span>
                    <span className="border-b border-current">&nbsp;</span>

                    <span>Email</span>
                    <span className="border-b border-current">
                        <Placeholder
                            value={legalDocument.representative_email}
                            fallback="[SIGNER EMAIL]"
                            focusTargetId={FIELD_IDS.representative_email}
                        />
                    </span>

                    <span>Date</span>
                    <span className="border-b border-current">{today}</span>
                </div>
            </div>
            <div>
                <div className="font-semibold mb-2">PostHog, Inc.</div>
                <div className="grid grid-cols-[minmax(100px,200px)_1fr] items-baseline gap-y-3">
                    <span>Signature</span>
                    <span className="border-b border-current">&nbsp;</span>
                    <span>Representative</span>
                    <span className="border-b border-current">Charles Cook, VP Operations</span>
                    <span>Date</span>
                    <span className="border-b border-current">{today}</span>
                </div>
            </div>
        </div>
    )
}
