import { useValues } from 'kea'

import { Link } from 'lib/lemon-ui/Link'

import posthogLogo from 'public/posthog-logo.svg'

import { FIELD_IDS } from '../../../scenes/legalDocumentsConstants'
import { legalDocumentsLogic } from '../../../scenes/legalDocumentsLogic'
import { Placeholder } from '../../base/Placeholder'
import { SignatureBlock } from '../../base/SignatureBlock'

interface DPALegalPreviewProps {
    /** When true, applies the serif "lawyer" styling; otherwise the default "pretty" layout. */
    lawyerMode?: boolean
}

export function DPALegalPreview({ lawyerMode = false }: DPALegalPreviewProps): JSX.Element {
    const { legalDocument } = useValues(legalDocumentsLogic)
    const { company_name, company_address, representative_name } = legalDocument
    const CompanyPlaceholder = (
        <Placeholder value={company_name} fallback="[COMPANY NAME]" focusTargetId={FIELD_IDS.company_name} />
    )

    return (
        <div
            className={`legal-document-preview prose prose-sm dark:prose-invert max-w-none ${
                lawyerMode ? 'legal-document-preview--lawyer' : ''
            }`}
        >
            {!lawyerMode && <img src={posthogLogo} alt="PostHog logo" width={157} className="my-6 not-prose" />}
            <h3>Data Processing Agreement — PostHog, Inc.</h3>
            <p>
                This Data Processing Agreement ("<strong>Agreement</strong>") forms part of the Contract for Services ("
                <strong>Principal Agreement</strong>") between {CompanyPlaceholder} (the "<strong>Company</strong>") and{' '}
                <strong>PostHog, Inc.</strong> (the "<strong>Processor</strong>") (together as the "
                <strong>Parties</strong>").
            </p>
            <p>
                In the event of a conflict between this Agreement and the provisions of related agreements, including
                the Principal Agreement, the terms of this Agreement shall prevail.
            </p>
            <p>WHEREAS</p>
            <p>(A) The Company acts as a Controller.</p>
            <p>
                (B) The Company wishes to subcontract certain Services, which imply the processing of personal data, to
                the Processor.
            </p>
            <p>
                (C) The Parties seek to implement a data processing agreement that complies with applicable Data
                Protection Laws (as defined below).
            </p>
            <p>(D) The Parties wish to lay down their rights and obligations.</p>
            <p>IT IS AGREED AS FOLLOWS:</p>

            <h4>1. Definitions and Interpretation</h4>
            <p>
                1.1. Unless otherwise defined herein, capitalized terms and expressions used in this Agreement shall
                have the following meaning:
            </p>
            <p>
                1.1.1. "<strong>Agreement</strong>" means this Data Processing Agreement and all Annexes;
            </p>
            <p>
                1.1.2. "<strong>Company Personal Data</strong>" means any Personal Data relating to Company's end users
                provided to or Processed by the Processor on behalf of the Company pursuant to or in connection with the
                Principal Agreement;
            </p>
            <p>
                1.1.3. "<strong>Data Protection Laws</strong>" means all applicable laws relating to Processing of
                Personal Data and privacy that may exist in any relevant jurisdiction, including European Data
                Protection Laws and US Data Protection Laws;
            </p>
            <p>
                1.1.4. "<strong>EEA</strong>" means the European Economic Area;
            </p>
            <p>
                1.1.5. "<strong>EU Personal Data</strong>" means the Processing of Personal Data by the Processor to
                which data protection legislation of the European Union, or of a Member State of the European Union or
                EEA, applies;
            </p>
            <p>
                1.1.6. "<strong>European Data Protection Laws</strong>" means the GDPR, UK Data Protection Act 2018, the
                UK GDPR, ePrivacy Directive 2002/58/EC, FADP, and any associated or additional legislation in force in
                the EU, EEA, Member States of the European Union, Switzerland, and the United Kingdom as amended,
                replaced or superseded from time to time;
            </p>
            <p>
                1.1.7. "<strong>FADP</strong>" means the Swiss Federal Act on Data Protection and its Ordinances, as
                amended from time to time;
            </p>
            <p>
                1.1.8. "<strong>FDPIC</strong>" means the Swiss Federal Data Protection and Information Commissioner;
            </p>
            <p>
                1.1.9. "<strong>GDPR</strong>" General Data Protection Regulation EU2016/679;
            </p>
            <p>
                1.1.10. "<strong>UK GDPR</strong>" means General Data Protection Regulation (EU) 2016/679 as applicable
                as part of UK domestic law by virtue of section 3 of the European Union (Withdrawal) Act 2018 and as
                amended by the Data Protection, Privacy and Electronic Communications (Amendments etc) (EU Exit)
                Regulations 2019 (as amended);
            </p>
            <p>
                1.1.11. "<strong>US Data Protection Laws</strong>" means all data privacy, data protection, and
                cybersecurity laws, rules, and regulations of the United States applicable to the Processing of Personal
                Data under the Principal Agreement, including the CCPA, CPA, CTDPA, UCPA, and VACDPA, and any binding
                regulations promulgated thereunder.
            </p>
            <p>
                1.1.12. "<strong>Protected Area</strong>" means the member states of the European Union and the EEA (and
                any country, territory, sector or international organization in respect of which an adequacy decision
                under Article 45 GDPR is in force); the United Kingdom (and any country, territory, sector or
                international organization in respect of which an adequacy decision under UK adequacy regulations is in
                force); and in the case of Swiss Personal Data, any country, territory, sector or international
                organization which is recognized as adequate by the FDPIC or the Swiss Federal Council.
            </p>
            <p>
                1.1.13. "<strong>Personal Data</strong>" means any information provided by Company to Processor that is
                protected as "personal data," "personal information," "personally identifiable information," or similar
                terms defined in Data Protection Laws.
            </p>
            <p>
                1.1.14. "<strong>Services</strong>" means the product and data analytics services the Processor provides
                pursuant to the Principal Agreement, including testing, support, product development, service
                improvement, benchmarking, troubleshooting, and security activities, and which may include AI and
                machine learning tools ("<strong>AI Features</strong>") if enabled for the Company depending on their
                use of the services.
            </p>
            <p>
                1.1.15. "<strong>Subprocessor</strong>" means any person appointed by or on behalf of Processor to
                Process Personal Data on behalf of the Company in connection with the Agreement.
            </p>
            <p>
                1.1.16. "<strong>Standard Contractual Clauses</strong>" means (1) in respect of UK Personal Data, the
                International Data Transfer Addendum to the EU Standard Contractual Clauses; (2) in respect of EU
                Personal Data, the standard contractual clauses for the transfer of personal data to third countries
                pursuant to the GDPR, adopted by the European Commission under Commission Implementing Decision (EU)
                2021/914, module 2 only; and (3) in respect of Swiss Personal Data, the EU Standard Contractual Clauses
                with the necessary adaptations and amendments for the FADP as required by the FDPIC.
            </p>

            <h4>2. Processing of Company Personal Data</h4>
            <p>
                2.1. The Company shall: (a) ensure that any and all information or data, including Company Personal
                Data, is collected, processed, transferred and used in full compliance with Data Protection Laws; (b) be
                solely responsible for ensuring that it has all necessary authorizations and consents from any Data
                Subjects to Process Company Personal Data and in particular any consents needed to meet the cookie
                requirements in the ePrivacy Directive 2002/58/EC; (c) instruct the Processor to process Company
                Personal Data to provide the Services.
            </p>
            <p>
                2.2. Processor shall: (a) comply with all applicable Data Protection Laws in the Processing of Company
                Personal Data; (b) not Process Company Personal Data other than on the Company's documented
                instructions; (c) notify the Company immediately if an instruction given by the Company infringes
                applicable Data Protection Laws; (d) not directly or indirectly sell or share any Personal Data.
            </p>
            <p>
                2.3. Annex I A sets out the subject-matter and duration of the processing, the nature and purpose of the
                processing, the type of personal data and categories of data subjects.
            </p>
            <p>
                2.4. Processor acknowledges that it is a Service Provider and that all Personal Data received from
                Company shall be regarded by Processor as strictly confidential.
            </p>
            <p>
                2.5. Processor shall not directly or indirectly sell any Personal Data, or retain, use, or disclose any
                Personal Data for any purpose other than for the purpose of performing services for Company.
            </p>

            <h4>3. Processor Personnel & Confidentiality</h4>
            <p>
                3.1. Processor shall take reasonable steps to ensure the reliability of any personnel who may have
                access to the Company Personal Data, ensuring that all such individuals are subject to confidentiality
                undertakings or professional or statutory obligations of confidentiality.
            </p>

            <h4>4. Security</h4>
            <p>
                4.1. Taking into account the state of the art, the costs of implementation and the nature, scope,
                context and purposes of Processing as well as the risk of varying likelihood and severity for the rights
                and freedoms of natural persons, Processor shall in relation to the Company Personal Data implement
                appropriate technical and organizational measures to ensure a level of security appropriate to that
                risk, including the measures referred to in Article 32(1) of the GDPR and UK GDPR. These measures
                include those at Annex II.
            </p>

            <h4>5. Subprocessing</h4>
            <p>
                5.1. The Company provides Processor with general authorization to engage the Subprocessors set out on{' '}
                <Link to="https://posthog.com/subprocessors">https://posthog.com/subprocessors</Link>.
            </p>
            <p>
                5.2. Processor shall enter into a written contract with any Subprocessor that imposes equivalent
                data-protection obligations. Where the Subprocessor fails, Processor remains fully liable.
            </p>
            <p>
                5.3. Processor may update the list of Subprocessors, providing the Company with notice (and an
                opportunity to object) at least fourteen (14) days in advance.
            </p>
            <p>
                5.4. If the Company objects to a Subprocessor, the Company shall notify Processor within seven (7) days;
                Processor shall use efforts to address the objection via cancellation, alternatives, or corrective
                steps; if none are reasonably available within thirty (30) days, the Company may terminate the affected
                Service.
            </p>

            <h4>6. Data Subject Rights and Cooperation</h4>
            <p>
                6.1. Taking into account the nature of the Processing, Processor shall assist the Company by
                implementing appropriate technical and organizational measures to respond to requests to exercise Data
                Subject rights under applicable Data Protection Laws.
            </p>
            <p>
                6.2. Processor shall notify Company if it receives a request from a Data Subject and not respond except
                on the documented instructions of Company.
            </p>
            <p>
                6.3. Processor shall provide information regarding the Service to enable the Company to carry out data
                protection impact assessments or prior consultations and meet its obligations under Article 32 GDPR/UK
                GDPR.
            </p>
            <p>
                6.4. To the extent that assistance is not included within the Services, the Processor may charge a
                reasonable fee, save where assistance is required as a result of the Processor's own acts or omissions.
            </p>

            <h4>7. Personal Data Breach</h4>
            <p>
                7.1. Processor shall notify Company without undue delay upon becoming aware of a Personal Data Breach,
                providing sufficient information to allow Company to meet reporting obligations.
            </p>
            <p>
                7.2. Processor shall cooperate with the Company and take reasonable commercial steps as directed by
                Company to assist in investigation, mitigation and remediation.
            </p>

            <h4>8. Audits</h4>
            <p>
                8.1. The Processor shall make available to the Company all information reasonably necessary to
                demonstrate compliance with this Agreement and, at the cost of the Company, allow for and contribute to
                audits.
            </p>

            <h4>9. Deletion or Return of Company Personal Data</h4>
            <p>
                9.1. At the end of the Services, upon the Company's request, Processor shall securely return or delete
                all copies of the Company Personal Data unless applicable laws require storage.
            </p>

            <h4>10. Data Center Location and Transfers Outside of the Protected Area</h4>
            <p>
                10.1. <strong>Storage of Personal Data.</strong> Company Personal Data will be housed in data centers
                located in the Data Center Location set out in the Principal Agreement.
            </p>
            <p>
                10.2. <strong>Transfers.</strong> The Company acknowledges that the Processor will Process the Company
                Personal Data outside of the Protected Area including in the US and elsewhere as identified on the
                Subprocessor Page.
            </p>
            <p>
                10.3. <strong>Data Privacy Framework.</strong> Processor confirms that it participates in the EU-US Data
                Privacy Framework, the UK Extension, and the Swiss-U.S. Data Privacy Framework (the "DPF").
            </p>
            <p>
                10.4. <strong>Standard Contractual Clauses.</strong> The parties agree to comply with the obligations
                set out in the Standard Contractual Clauses with the Company as the "data exporter" and the Processor as
                the "data importer".
            </p>
            <p>
                10.5. For EU Standard Contractual Clauses: option 2 (general written authorization for subprocessors)
                applies; clauses 9 and 13 supervisory authority per GDPR; clauses 17-18 governed by Ireland and Irish
                courts.
            </p>
            <p>
                10.6. For UK Standard Contractual Clauses: details per Annex I; Addendum appended to EU SCCs with module
                2.
            </p>
            <p>
                10.7. For Swiss Personal Data: EU SCCs apply with FADP adaptations (references to GDPR interpreted as
                FADP, etc.).
            </p>
            <p>
                10.8. In the event of any conflict between this Agreement and the Standard Contractual Clauses, the
                Standard Contractual Clauses shall prevail.
            </p>
            <p>
                10.9. If a relevant adequacy decision is invalidated or Processor ceases to participate in the DPF, the
                parties will agree to use a suitable alternative transfer solution.
            </p>

            <h4>11. General Terms</h4>
            <p>
                11.1. <em>Confidentiality.</em> Each party must keep this Agreement and information it receives about
                the other party and its business confidential, except where disclosure is required by law or the
                information is already in the public domain.
            </p>
            <p>
                11.2. <em>Notices.</em> All notices must be in writing and delivered personally, by post, or by email to
                the address set out in the heading of this Agreement.
            </p>
            <p>
                11.3. <em>Governing Law and Jurisdiction.</em> This Agreement is governed by the laws and choice of
                jurisdiction stipulated in the Principal Agreement.
            </p>

            <p>IN WITNESS WHEREOF, this Agreement is entered into with effect from the date first set out below.</p>

            <SignatureBlock />

            <h4 className="text-center mt-10">ANNEX I</h4>
            <p>
                <strong>A. Processing Activities.</strong> The personal data shall be processed in order to allow
                Processor to provide the Services — a software platform that equips developers to build successful
                products, including product analytics, insights, heatmaps, session recording and feature flags;
                troubleshooting, benchmarking, product development, security activities, and service improvement.
                Duration: for the duration of the Principal Agreement. Categories of data subjects: Company's end users
                (prospects, customers and contractors). Categories of personal data: personal details and contact
                information; documents and content uploaded to the Services. Sensitive categories: N/A.
            </p>
            <p>
                <strong>B. List of Parties.</strong> The data exporter is the Company at{' '}
                <Placeholder
                    value={company_address}
                    fallback="[COMPANY ADDRESS]"
                    focusTargetId={FIELD_IDS.company_address}
                />
                ; contact person{' '}
                <Placeholder
                    value={representative_name}
                    fallback="[REPRESENTATIVE NAME]"
                    focusTargetId={FIELD_IDS.representative_name}
                />
                ; role controller. The data importer is the Processor at 2261 Market St., #4008, San Francisco, CA
                94114, USA; contact person privacy@posthog.com; role processor.
            </p>
            <p>
                <strong>C. Description of Transfer.</strong> Categories of data subjects and personal data transferred:
                see Annex I.A. Sensitive data: N/A. Frequency: continuous basis. Nature, purpose, retention and subject
                matter: see Annex I.A.
            </p>

            <h4 className="text-center mt-10">ANNEX II — Technical and Organizational Security Measures</h4>
            <p>
                See{' '}
                <Link to="https://posthog.com/handbook/company/security" target="_blank">
                    https://posthog.com/handbook/company/security
                </Link>
                .
            </p>
        </div>
    )
}
