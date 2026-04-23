import { useValues } from 'kea'

import { FIELD_IDS } from '../../../scenes/legalDocumentsConstants'
import { legalDocumentsLogic } from '../../../scenes/legalDocumentsLogic'
import { Placeholder } from '../../base/Placeholder'
import { SignatureBlock } from '../../base/SignatureBlock'

export function BAAPreview(): JSX.Element {
    const { legalDocument } = useValues(legalDocumentsLogic)
    const { company_name, representative_name, representative_title } = legalDocument

    return (
        <div className="legal-document-preview prose prose-sm dark:prose-invert max-w-none">
            <h3>Business Associate Agreement — PostHog, Inc.</h3>
            <p>
                This Business Associate Agreement ("Agreement") is entered into by and between{' '}
                <Placeholder value={company_name} fallback="[COMPANY NAME]" focusTargetId={FIELD_IDS.company_name} />{' '}
                ("Covered Entity") and <strong>PostHog, Inc.</strong> ("Business Associate").
            </p>
            <p>
                This Agreement is effective as of the date signed by Covered Entity's representative,{' '}
                <Placeholder
                    value={representative_name}
                    fallback="[REPRESENTATIVE NAME]"
                    focusTargetId={FIELD_IDS.representative_name}
                />
                , titled{' '}
                <Placeholder
                    value={representative_title}
                    fallback="[REPRESENTATIVE TITLE]"
                    focusTargetId={FIELD_IDS.representative_title}
                />
                .
            </p>
            <p>
                This Agreement is entered into for the purpose of ensuring that Business Associate will appropriately
                safeguard Protected Health Information (PHI) as required by the Health Insurance Portability and
                Accountability Act of 1996 (HIPAA).
            </p>
            <p>
                Capitalized terms used in this Agreement and not otherwise defined shall have the meanings ascribed to
                them in HIPAA.
            </p>

            <p>
                This Business Associate Amendment (this "BAA"), effective as of the date electronically agreed and
                excepted by you (the "BAA Effective Date"), is entered into by and between PostHog, Inc. ("PostHog",
                "we", or "us") and the party that electronically accepts or otherwise agrees or opts-in to this BAA
                ("Customer", or "you").
            </p>
            <p>
                You have entered into one or more agreements with us (each, as amended from time to time, an
                "Agreement") governing the provision of our real-time error tracking, crash reporting, and visibility
                service more fully described at posthog.com (the "Service"). This BAA will amend the terms of the
                Agreement to reflect the parties' rights and responsibilities with respect to the processing and
                security of your Protected Health Information (defined below) under the Agreement.
            </p>
            <p>
                This BAA is only available to customers on the Teams Plan, as defined below, and is effective only if
                the Customer has the required add-on in place at the time of signing. By signing this BAA, the Customer
                represents and warrants that they meet the requirements of the Teams Plan. This BAA shall be null, void,
                and of no effect if the Customer does not meet those requirements at the time of signing.
            </p>

            <p>
                <strong>Definitions.</strong> For the purposes of this BAA, capitalized terms shall have the meanings
                ascribed to them below. All capitalized terms used but not otherwise defined herein will have the
                meaning ascribed to them by HIPAA.
            </p>
            <p>
                "HIPAA" means the Health Insurance Portability and Accountability Act of 1996 and regulations
                promulgated thereunder, and the HITECH Act.
            </p>
            <p>
                "HITECH Act" means the security provisions of the American Recovery and Reinvestment Act of 2009, also
                known as the Health Information Technology for Economic and Clinical Health Act.
            </p>
            <p>
                "Protected Health Information" or "PHI" is any information, whether oral or recorded in any form or
                medium that is created, received, maintained, or transmitted by PostHog for or on behalf of Customer
                pursuant to this BAA, that identifies an individual or might reasonably be used to identify an
                individual and relates to: (i) the individual's past, present or future physical or mental health; (ii)
                the provision of health care to the individual; or (iii) the past, present or future payment for health
                care.
            </p>
            <p>"Secretary" shall refer to the Secretary of the U.S. Department of Health and Human Services.</p>
            <p>
                "Unsecured PHI" shall mean PHI that is not rendered unusable, unreadable, or indecipherable to
                unauthorized individuals through the use of a technology or methodology specified by the Secretary
                (e.g., encryption).
            </p>
            <p>"Teams Plan" shall mean the plan that the Customer must be paying for to receive coverage with a BAA.</p>

            <p>
                <strong>Customer Assurances.</strong> Customer represents and warrants that it is a "Covered Entity" or
                a "Business Associate" as defined by HIPAA; that it shall comply with HIPAA in its use of the Service,
                including utilizing tools made available in the Service to facilitate Customer's compliance with HIPAA's
                minimum necessary requirement; that it will not request that PostHog take any action that would violate
                HIPAA if performed by Customer; and that it will not request PostHog to use or disclose PHI in any
                manner that would violate applicable federal or state laws.
            </p>

            <p>
                <strong>PostHog's Assurances.</strong> PostHog (1) shall not use or disclose PHI, other than as
                permitted or required by this BAA and Agreement, or as required by law; (2) shall not use or disclose
                PHI in any manner that violates applicable federal or state laws or would violate such laws if used or
                disclosed in such manner by Customer; and (3) shall only use and disclose the minimum necessary PHI for
                its specific purposes.
            </p>
            <p>
                PostHog may use the information received from Customer if necessary for (i) the proper management and
                administration of PostHog; or (ii) to carry out the legal responsibilities of PostHog. PostHog may
                disclose PHI for its proper management and administration provided that: (1) disclosures are required by
                law; or (2) PostHog obtains reasonable assurances from the person or entity to whom the information is
                disclosed that it will remain confidential and used or further disclosed only as required by law or for
                the purpose for which it was disclosed, and the person or entity notifies PostHog of any instances of
                which it is aware in which the confidentiality of the information has been breached.
            </p>
            <p>
                PostHog will report to Customer any use or disclosure of PHI not provided for by this BAA of which
                PostHog becomes aware, including breaches of Unsecured PHI.
            </p>
            <p>
                PostHog will ensure that any subcontractors that create, receive, maintain, or transmit PHI on PostHog's
                behalf agree to the same restrictions and conditions that apply to PostHog with respect to such PHI.
            </p>
            <p>
                Upon request of Customer or an individual, PostHog will promptly provide information to Customer as may
                be reasonably necessary to facilitate Customer's compliance with its obligations to provide access to
                PHI (45 CFR 164.524), amend PHI (45 CFR 164.526), and provide an accounting of disclosures (45 CFR
                164.528).
            </p>
            <p>
                PostHog will comply with HIPAA security standards for electronic PHI. All privacy and security measures
                are found at https://posthog.com/docs/privacy. PostHog will make its internal practices, books, and
                records relating to the use and disclosure of PHI available to the Secretary for the purpose of
                determining Customer's compliance with HIPAA. PostHog will use appropriate safeguards to prevent use or
                disclosure of the PHI other than as provided for by this BAA and to comply with the HIPAA Security Rule
                (Subpart C of 45 CFR Part 164).
            </p>

            <p>
                <strong>Privacy Rule.</strong> Both parties are committed to complying with all federal and state laws
                governing the confidentiality and privacy of health information, including the Standards for Privacy of
                Individually Identifiable Health Information found at 45 CFR Part 160 and Part 164, Subparts A and E
                (the "Privacy Rule"); and both parties intend to protect the privacy and provide for the security of
                Protected Health Information disclosed to Business Associate pursuant to the terms of this Agreement,
                HIPAA and other applicable laws.
            </p>

            <p>
                <strong>Term.</strong> This BAA shall be effective on the BAA Effective Date, and shall remain in effect
                until the earlier of: (i) the termination or expiration of the Agreement; (ii) the termination of this
                BAA in accordance with the Termination section; or (iii) the Customer unsubscribes from the relevant
                Teams Plan.
            </p>

            <p>
                <strong>Termination.</strong> Customer may terminate this BAA upon written notice if PostHog materially
                breaches a term of this BAA and fails to cure the breach within thirty (30) days. PostHog may terminate
                this BAA upon written notice if Customer agrees to restrictions that impact PostHog's ability to perform
                its obligations, agrees to restrictions that increase PostHog's cost of performance, or fails to meet
                its obligations under HIPAA. The parties may also terminate by mutual consent.
            </p>

            <p>
                <strong>Reporting Disclosures of PHI and Security Incidents.</strong> Business Associate will report to
                Covered Entity in writing any use or disclosure of PHI not provided for by this BAA of which it becomes
                aware and agrees to report any Security Incident affecting Electronic PHI within five business days of
                becoming aware.
            </p>

            <p>
                <strong>Suspension of Disclosure.</strong> In the event that Customer reasonably determines that PostHog
                has breached its obligations under this BAA, Customer may immediately stop all further disclosures of
                PHI to PostHog until the breach has been resolved.
            </p>

            <p>
                <strong>Return or Destruction of PHI upon Termination.</strong> Upon termination, unless otherwise
                directed, PostHog will return or destroy all PHI received from, created by, or received on behalf of
                Customer; provided that if PostHog deems return or destruction unfeasible, the terms of this BAA will
                survive termination and PostHog will use or disclose such PHI solely as permitted by law.
            </p>

            <p>
                <strong>Miscellaneous.</strong> There are no third party beneficiaries to this BAA. Except as expressly
                provided, nothing in this BAA will be deemed to waive or modify any provisions of the Agreement
                (including limitations of liability). In the event of a conflict between the terms of this BAA and the
                terms of the Agreement, the terms of this BAA will control. All references to PHI in this BAA shall
                include electronic PHI. Any ambiguity shall be resolved in favor of a meaning that permits PostHog to
                comply with HIPAA.
            </p>

            <SignatureBlock />
        </div>
    )
}
