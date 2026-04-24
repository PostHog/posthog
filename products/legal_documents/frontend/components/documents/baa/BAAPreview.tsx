import { useValues } from 'kea'

import { FIELD_IDS } from '../../../scenes/legalDocumentsConstants'
import { legalDocumentsLogic } from '../../../scenes/legalDocumentsLogic'
import { Placeholder } from '../../base/Placeholder'
import { SignatureBlock } from '../../base/SignatureBlock'

export function BAAPreview(): JSX.Element {
    const { legalDocument } = useValues(legalDocumentsLogic)
    const { company_name } = legalDocument
    const CompanyPlaceholder = (
        <Placeholder value={company_name} fallback="[COMPANY NAME]" focusTargetId={FIELD_IDS.company_name} />
    )

    return (
        <div className="legal-document-preview prose prose-sm dark:prose-invert max-w-none">
            <h3>Business Associate Agreement — PostHog Inc.</h3>
            <p>
                This Business Associate Amendment (this "<strong>BAA</strong>"), effective as of the date electronically
                agreed and accepted by you (the "<strong>BAA Effective Date</strong>"), is entered into by and between
                PostHog Inc ("<strong>PostHog</strong>", "<strong>we</strong>", or "<strong>us</strong>") and the party
                that electronically accepts or otherwise agrees or opts-in to this BAA ("<strong>Customer</strong>", or
                "<strong>you</strong>").
            </p>
            <p>
                You have entered into one or more agreements with us (each, as amended from time to time, an "
                <strong>Agreement</strong>") governing the provision of our real-time error tracking, crash reporting,
                and visibility service more fully described at www.posthog.com (the "<strong>Service</strong>"). This
                BAA will amend the terms of the Agreement to reflect the parties' rights and responsibilities with
                respect to the processing and security of your Protected Health Information (defined below) under the
                Agreement; provided, however, that this BAA, and any obligations relating to compliance with HIPAA
                hereunder, do not apply with respect to any Services (or features or functionality thereof) that PostHog
                designates as not subject to this BAA, as indicated in the applicable service interface, guidance,
                documentation, ordering materials, or otherwise, even if such Services involve the processing of PHI. If
                you are accepting this BAA in your capacity as an employee, consultant or agent of Customer (
                {CompanyPlaceholder}), you represent that you are an employee, consultant or agent of Customer, and that
                you have the authority to bind Customer to this BAA.
            </p>
            <p>
                This BAA is only available to customers with the applicable Platform Package, as defined below, and is
                effective only if the Customer has the required add-on in place at the time of signing. By signing this
                BAA, the Customer represents and warrants that they meet the requirements of and have entered into the
                applicable Platform Package. This BAA shall be null, void, and of no effect if the Customer does not
                meet those requirements at the time of signing, regardless of whether this BAA has been electronically
                executed.
            </p>
            <p>
                This BAA applies only to PostHog's processing of PHI for Customer in Customer's capacity as a Covered
                Entity or Business Associate.
            </p>
            <p>
                For good and valuable consideration, the sufficiency of which is hereby acknowledged, the parties agree
                as follows:
            </p>

            <h4>1. Definitions</h4>
            <p>
                For the purposes of this BAA, capitalized terms shall have the meanings ascribed to them below. All
                capitalized terms used but not otherwise defined herein will have the meaning ascribed to them by HIPAA.
            </p>
            <p>
                "<strong>HIPAA</strong>" means the Health Insurance Portability and Accountability Act of 1996 and
                regulations promulgated thereunder, and the HITECH Act;
            </p>
            <p>
                "<strong>HITECH Act</strong>" means the security provisions of the American Recovery and Reinvestment
                Act of 2009, also known as the Health Information Technology for Economic and Clinical Health Act;
            </p>
            <p>
                "<strong>Protected Health Information</strong>" or "<strong>PHI</strong>" is any information, whether
                oral or recorded in any form or medium that is created, received, maintained, or transmitted by PostHog
                for or on behalf of Customer pursuant to this BAA, that identifies an individual or might reasonably be
                used to identify an individual and relates to: (i) the individual's past, present or future physical or
                mental health; (ii) the provision of health care to the individual; or (iii) the past, present or future
                payment for health care;
            </p>
            <p>
                "<strong>Secretary</strong>" shall refer to the Secretary of the U.S. Department of Health and Human
                Services;
            </p>
            <p>
                "<strong>Unsecured PHI</strong>" shall mean PHI that is not rendered unusable, unreadable, or
                indecipherable to unauthorized individuals through the use of a technology or methodology specified by
                the Secretary (e.g., encryption). This definition applies to both hard copy PHI and electronic PHI.
            </p>
            <p>
                "<strong>Platform Package</strong>" shall mean the add-on that the Customer must be paying for to
                receive coverage with a BAA (either the Boost, Scale or Enterprise add-on
                (https://posthog.com/platform-packages)).
            </p>

            <h4>2. Customer Assurances</h4>
            <p>Customer represents and warrants as follows:</p>
            <p>(a) That it is a "Covered Entity" or a "Business Associate" as defined by HIPAA;</p>
            <p>
                (b) That it shall comply with HIPAA in its use of the Service, including utilizing tools made available
                in the Service to facilitate Customer's compliance with HIPAA's minimum necessary requirement;
            </p>
            <p>
                (c) That it will not request that PostHog take any action that would violate HIPAA if performed by
                Customer; and
            </p>
            <p>
                (d) That it will not request PostHog to use or disclose PHI in any manner that would violate applicable
                federal or state laws if such use or disclosure were made by Customer.
            </p>

            <h4>3. PostHog's Assurances</h4>
            <p>
                (a) PostHog (1) shall not use or disclose PHI, other than as permitted or required by this BAA and
                Agreement, or as required by law; (2) shall not use or disclose PHI in any manner that violates
                applicable federal or state laws or would violate such laws if used or disclosed in such manner by
                Customer; and (3) shall only use and disclose the minimum necessary PHI for its specific purposes.
                Customer agrees that PostHog may rely on Customer's instructions to determine if uses and disclosures
                meet this minimum necessary requirement.
            </p>
            <p>
                (b) PostHog may use the information received from Customer if necessary for (i) the proper management
                and administration of PostHog; or (ii) to carry out the legal responsibilities of PostHog. PostHog may
                disclose PHI for its proper management and administration provided that: (1) disclosures are required by
                law; or (2) PostHog obtains reasonable assurances from the person or entity to whom the information is
                disclosed that it will remain confidential and used or further disclosed only as required by law or for
                the purpose for which it was disclosed to the person or entity, and the person or entity notifies
                PostHog of any instances of which it is aware in which the confidentiality of the information has been
                breached.
            </p>
            <p>
                (c) PostHog will report to Customer any use or disclosure of PHI not provided for by this BAA of which
                PostHog becomes aware, including breaches of Unsecured PHI subject to the following:
            </p>
            <p>
                (i) The parties acknowledge that unsuccessful attempts to access Unsecured PHI (e.g., pings and other
                broadcast attacks on a firewall, denial of service attacks, port scans, unsuccessful login attempts)
                occur within the normal course of business and the parties stipulate and agree that this paragraph
                constitutes notice by PostHog to Customer for such unsuccessful attempts; and
            </p>
            <p>
                (ii) Communications by or on behalf of PostHog with Customer in connection with this Section 3(c) shall
                not be construed as an acknowledgment by PostHog of any fault or liability with respect to the breaches
                of Unsecured PHI.
            </p>
            <p>
                (d) PostHog will ensure that any subcontractors that create, receive, maintain, or transmit PHI on
                PostHog's behalf agree to the same restrictions and conditions that apply to PostHog with respect to
                such PHI.
            </p>
            <p>
                (e) Upon request of Customer or an individual, PostHog will promptly provide information to Customer as
                may be reasonably necessary to facilitate Customer's compliance with its obligation to: (i) make
                available to requesting individuals a copy of any PHI about such individuals held by PostHog in a
                designated record set, in accordance with 45 CFR 164.524; (ii) amend PHI or records about the requesting
                individual held by PostHog in a designated record set, in accordance with 45 CFR 164.526; and (iii)
                provide to requesting individuals an accounting of disclosures of PHI about such individuals made by
                Customer in the six (6) years prior to the date of request, in accordance with 45 CFR 164.528.
            </p>
            <p>
                (f) In the event that any individual requests from PostHog access, amendment, or an accounting of PHI,
                PostHog shall forward such request to Customer within five (5) business days. Customer shall be
                responsible for responding to the individual's request and Customer agrees that PostHog may respond to
                the individual directing them to make such request to Customer.
            </p>
            <p>
                (g) PostHog will comply with HIPAA security standards for electronic PHI. All Privacy and security
                measures are found at https://posthog.com/docs/privacy
            </p>
            <p>
                (h) PostHog will make its internal practices, books, and records relating to the use and disclosure of
                PHI received from, or created or received by PostHog on behalf of, Customer available to the Secretary
                for the purpose of determining Customer's compliance with HIPAA.
            </p>
            <p>
                (i) To the extent that PostHog carries out Customer's obligations under HIPAA regulations, PostHog will
                comply with the requirements of this Section 3 that apply to Customer in the performance of such
                obligations.
            </p>
            <p>
                (j) PostHog will use appropriate safeguards to prevent use or disclosure of the PHI other than as
                provided for by this BAA and to comply with the HIPAA Security Rule (Subpart C of 45 CFR Part 164).
            </p>

            <h4>4. Privacy Rule</h4>
            <p>
                (a) Both Parties are committed to complying with all federal and state laws governing the
                confidentiality and privacy of health information, including, but not limited to, the Standards for
                Privacy of Individually Identifiable Health Information found at 45 CFR Part 160 and Part 164, Subparts
                A and E (collectively, the "<strong>Privacy Rule</strong>"); and
            </p>
            <p>
                (b) Both Parties intend to protect the privacy and provide for the security of Protected Health
                Information disclosed to Business Associate pursuant to the terms of this Agreement, HIPAA and other
                applicable laws.
            </p>

            <h4>5. Term</h4>
            <p>
                This BAA shall be effective on the BAA Effective Date, and shall remain in effect until the earlier of:
                (i) the termination or expiration of the Agreement; or (ii) the termination of this BAA in accordance
                with Section 6, below; (iii) the Customer unsubscribes from the relevant Platform Package to be allowed
                the coverage of this BAA.
            </p>

            <h4>6. Termination</h4>
            <p>
                Customer may terminate this BAA upon written notice if PostHog materially breaches a term of this BAA,
                and fails to cure the breach within thirty (30) days of receiving written notice of it. PostHog may
                terminate this BAA upon written notice if Customer either: (i) agrees to restrictions that impact
                PostHog's ability to perform its obligations under the Agreement; (ii) agrees to restrictions that
                increase PostHog's cost of performance under this BAA or the Agreement; or (iii) fails to meet its
                obligations under HIPAA. The Parties may also terminate this BAA upon mutual consent.
            </p>

            <h4>7. Reporting Disclosures of PHI and Security Incidents</h4>
            <p>
                Business Associate will report to Covered Entity in writing any use or disclosure of PHI not provided
                for by this BAA of which it becomes aware and Business Associate agrees to report to Covered Entity any
                Security Incident affecting Electronic PHI of Covered Entity of which it becomes aware. Business
                Associate agrees to report any such event within five business days of becoming aware of the event.
            </p>

            <h4>8. Suspension of Disclosure</h4>
            <p>
                In the event that Customer reasonably determines that PostHog has breached its obligations under this
                BAA, Customer may, in addition to its other rights set forth in this BAA, immediately stop all further
                disclosures of PHI to PostHog until the breach has been resolved.
            </p>

            <h4>9. Return or Destruction of PHI upon Termination</h4>
            <p>
                Upon termination of this BAA, unless otherwise directed by Customer, PostHog will return or destroy all
                PHI received from, created by, or received on behalf of, Customer and will not retain copies of any such
                PHI; provided that in the event PostHog deems return or destruction of such PHI unfeasible, the terms of
                this BAA will survive termination and, for as long as PostHog retains that PHI, PostHog will use or
                disclose it solely as permitted by law.
            </p>

            <h4>10. Miscellaneous</h4>
            <p>
                There are no third party beneficiaries to this BAA. Except as expressly provided herein, nothing in this
                BAA will be deemed to waive or modify any of the provisions of the Agreement (including limitations of
                liability), which otherwise remain in full force and effect. If you have entered into more than one
                Agreement with us, this BAA will amend each of the Agreements separately. In the event of a conflict or
                inconsistency between the terms of this BAA and the terms of the Agreement, the terms of this BAA will
                control. The parties recognize that electronic PHI is a subset of PHI and all references to PHI in this
                BAA shall include electronic PHI. A reference in this BAA to a section of HIPAA means the section as in
                effect or as amended, and for which compliance is required. Any ambiguity in this BAA shall be resolved
                in favor of a meaning that permits PostHog to comply with HIPAA. If any of the regulations promulgated
                under HIPAA are amended or interpreted in a manner that renders this BAA inconsistent therewith, the
                parties shall cooperate in good faith to amend this BAA to the extent necessary to comply with such
                amendments or interpretations.
            </p>

            <SignatureBlock />
        </div>
    )
}
