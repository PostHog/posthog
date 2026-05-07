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
    const { company_name, company_address, representative_email } = legalDocument
    const CompanyPlaceholder = (
        <Placeholder value={company_name} fallback="[COMPANY NAME]" focusTargetId={FIELD_IDS.company_name} />
    )
    const AddressPlaceholder = (
        <Placeholder value={company_address} fallback="[COMPANY ADDRESS]" focusTargetId={FIELD_IDS.company_address} />
    )
    const EmailPlaceholder = (
        <Placeholder
            value={representative_email}
            fallback="[SIGNER EMAIL]"
            focusTargetId={FIELD_IDS.representative_email}
        />
    )

    return (
        <div
            className={`legal-document-preview prose prose-sm dark:prose-invert max-w-none ${
                lawyerMode ? 'legal-document-preview--lawyer' : ''
            }`}
        >
            {!lawyerMode && <img src={posthogLogo} alt="PostHog logo" width={157} className="my-6 not-prose" />}
            <h3>Data Processing Agreement — PostHog Inc.</h3>
            <p>
                This Data Processing Agreement ("<strong>Agreement</strong>") forms part of the Contract for Services ("
                <strong>Principal Agreement</strong>") between {CompanyPlaceholder} (the "<strong>Company</strong>") and{' '}
                <strong>PostHog Inc.</strong> (the "<strong>Processor</strong>") (together as the "
                <strong>Parties</strong>").
            </p>
            <p>
                In the event of a conflict between this Agreement and the provisions of related agreements, including
                the Principal Agreement, the terms of this Agreement shall prevail.
            </p>
            <p>
                <strong>WHEREAS:</strong>
            </p>
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
            <p>
                <strong>IT IS AGREED AS FOLLOWS:</strong>
            </p>

            <h4>1. Definitions and Interpretation</h4>
            <p>
                Unless otherwise defined herein, capitalized terms and expressions used in this Agreement shall have the
                following meaning:
            </p>
            <p>
                "<strong>Agreement</strong>" means this Data Processing Agreement and all Annexes;
            </p>
            <p>
                "<strong>Company Personal Data</strong>" means any Personal Data relating to Company's end users
                provided to or Processed by the Processor on behalf of the Company pursuant to or in connection with the
                Principal Agreement;
            </p>
            <p>
                "<strong>Data Protection Laws</strong>" means all applicable laws relating to Processing of Personal
                Data and privacy that may exist in any relevant jurisdiction, including European Data Protection Laws
                and US Data Protection Laws;
            </p>
            <p>
                "<strong>EEA</strong>" means the European Economic Area;
            </p>
            <p>
                "<strong>EU Personal Data</strong>" means the Processing of Personal Data by the Processor to which data
                protection legislation of the European Union, or of a Member State of the European Union or EEA,
                applies;
            </p>
            <p>
                "<strong>European Data Protection Laws</strong>" means the GDPR, UK Data Protection Act 2018, the UK
                GDPR, ePrivacy Directive 2002/58/EC, FADP, and any associated or additional legislation in force in the
                EU, EEA, Member States of the European Union, Switzerland and the United Kingdom as amended, replaced or
                superseded from time to time;
            </p>
            <p>
                "<strong>FADP</strong>" means the Swiss Federal Act on Data Protection and its Ordinances, as amended
                from time to time;
            </p>
            <p>
                "<strong>FDPIC</strong>" means the Swiss Federal Data Protection and Information Commissioner;
            </p>
            <p>
                "<strong>GDPR</strong>" means the General Data Protection Regulation EU2016/679;
            </p>
            <p>
                "<strong>UK GDPR</strong>" means General Data Protection Regulation (EU) 2016/679 as applicable as part
                of UK domestic law by virtue of section 3 of the European Union (Withdrawal) Act 2018 and as amended by
                the Data Protection, Privacy and Electronic Communications (Amendments etc.) (EU Exit) Regulations 2019
                (as amended);
            </p>
            <p>
                "<strong>US Data Protection Laws</strong>" means all data privacy, data protection, and cybersecurity
                laws, rules, and regulations of the United States applicable to the Processing of Personal Data under
                the Principal Agreement. "US Data Protection Laws" may include, but is not limited to, the California
                Consumer Privacy Act of 2018, as amended by the California Privacy Rights Act of 2020 (together, the "
                <strong>CCPA</strong>"), the Colorado Privacy Act ("<strong>CPA</strong>"), the Connecticut Data Privacy
                Act ("<strong>CTDPA</strong>"), the Utah Consumer Privacy Act ("<strong>UCPA</strong>"), and the
                Virginia Consumer Data Protection Act ("<strong>VACDPA</strong>"), and any binding regulations
                promulgated thereunder, as amended or updated from time to time;
            </p>
            <p>
                "<strong>Protected Area</strong>" means (i) in the case of EU Personal Data, the member states of the
                European Union and the EEA and any country, territory, sector or international organization in respect
                of which an adequacy decision under Article 45 GDPR is in force or (ii) in the case of UK Personal Data,
                the United Kingdom and any country, territory, sector or international organization in respect of which
                an adequacy decision under UK adequacy regulations is in force; or (iii) in the case of Swiss Personal
                Data, any country, territory, sector or international organization which is recognized as adequate by
                the FDPIC or the Swiss Federal Council (as the case may be);
            </p>
            <p>
                "<strong>Personal Data</strong>" means any information provided by Company to Processor that is
                protected as "personal data," "personal information," "personally identifiable information," or similar
                terms defined in Data Protection Laws;
            </p>
            <p>
                "<strong>Services</strong>" means the product and data analytics services the Processor provides
                pursuant to the Principal Agreement, including but not limited to the provision of testing, support,
                product development, service improvement, benchmarking and troubleshooting and security activities on
                behalf of the Data Controller, and which may include AI and machine learning tools ("
                <strong>AI Features</strong>") if enabled for the Company depending on their use of the services;
            </p>
            <p>
                "<strong>Subprocessor</strong>" means any person appointed by or on behalf of Processor to Process
                Personal Data on behalf of the Company in connection with the Agreement;
            </p>
            <p>
                "<strong>Standard Contractual Clauses</strong>" means:
            </p>
            <p>
                in respect of UK Personal Data, the International Data Transfer Addendum to the EU Standard Contractual
                Clauses, issued by the Information Commissioner and laid before Parliament in accordance with s.119A of
                the Data Protection Act 2018 on 2 February 2022 ("<strong>UK Standard Contractual Clauses</strong>");
            </p>
            <p>
                in respect of EU Personal Data, the standard contractual clauses for the transfer of personal data to
                third countries pursuant to the GDPR, adopted by the European Commission under Commission Implementing
                Decision (EU) 2021/914 including the text from module 2 and no other modules and not including any
                clauses marked as optional, ("<strong>EU Standard Contractual Clauses</strong>");
            </p>
            <p>
                in respect of Swiss Personal Data, the EU Standard Contractual Clauses with the necessary adaptations
                and amendments for the purposes of the FADP as required by the FDPIC in its Statement of 27 August 2021;
            </p>
            <p>
                "<strong>Swiss Personal Data</strong>" means the Processing of Personal Data by the Processor to which
                the FADP applies;
            </p>
            <p>
                "<strong>UK Personal Data</strong>" means the Processing of Personal Data by the Processor to which the
                laws of the United Kingdom apply.
            </p>
            <p>
                The terms, "<strong>Controller</strong>", "<strong>Data Subject</strong>", "
                <strong>Member State</strong>
                ", "<strong>Personal Data</strong>", "<strong>Personal Data Breach</strong>", "
                <strong>Processing</strong>" and "<strong>Supervisory Authority</strong>" shall have the same meaning as
                in the GDPR and UK GDPR, and their cognate terms shall be construed accordingly with other Data
                Protection Laws. For example, Data Subject shall include such analogous terms as Consumer under US Data
                Protection Laws.
            </p>
            <p>
                The terms "<strong>sell</strong>," "<strong>sale</strong>," "<strong>share</strong>," and "
                <strong>sharing</strong>," and "<strong>Service Provider</strong>" shall have the same meanings as in
                the CCPA.
            </p>

            <h4>2. Processing of Company Personal Data</h4>
            <p>The Company shall:</p>
            <p>
                (a) ensure that any and all information or data, including without limitation Company Personal Data, is
                collected, processed, transferred and used in full compliance with Data Protection Laws;
            </p>
            <p>
                (b) be solely responsible for ensuring that it has obtained all necessary authorizations and consents
                from any Data Subjects to Process Company Personal Data and in particular any consents needed to meet
                the cookie requirements in the ePrivacy Directive 2002/58/EC and any associated national legislation;
            </p>
            <p>
                (c) instruct the Processor to process Company Personal Data to provide the Services. The Company
                acknowledges that if AI Features are enabled as part of the Services, such AI Features may use or rely
                on AI functionality (based on OpenAI's model or similar LLMs). Note that the Processor does not use any
                Company Personal Data to fine tune, train or develop its AI functionality or models for its own purposes
                and does not permit any third parties (including its Subprocessors) to do so.
            </p>
            <p>Processor shall:</p>
            <p>(a) comply with all applicable Data Protection Laws in the Processing of Company Personal Data;</p>
            <p>
                (b) not Process Company Personal Data other than on the relevant Company's documented instructions
                including with regard to data transfers outside of the Protected Area, unless required to do so by laws
                to which the Processor is subject; in such a case, Processor shall inform the Company of that legal
                requirement before Processing, unless that law prohibits such information on important grounds of public
                interest;
            </p>
            <p>
                (c) notify the Company immediately if, in the Processor's reasonable opinion, an instruction for the
                Processing of Personal Data given by the Company infringes applicable Data Protection Laws, it being
                acknowledged that the Processor shall not be obliged to undertake additional work or screening to
                determine if the Company's instructions are compliant;
            </p>
            <p>(d) not directly or indirectly sell or share any Personal Data.</p>
            <p>
                Annex I, Section A. sets out the subject-matter and duration of the processing, the nature and purpose
                of the processing, the type of personal data and categories of data subjects. The obligations and rights
                of the Company are as set out in this Agreement.
            </p>
            <p>
                Processor acknowledges that it is a Service Provider and that all Personal Data that it may receive from
                Company, Company's employees or consultants, or otherwise acquired by virtue of the performance of
                services under the Principal Agreement shall be regarded by Processor as strictly confidential and held
                by Processor in confidence.
            </p>
            <p>
                Processor shall not directly or indirectly sell any Personal Data, or retain, use, or disclose any
                Personal Data for any purpose other than for the purpose of performing services for Company; or retain,
                use, or disclose any Personal Data outside the scope of this Agreement or the Principal Agreement.
            </p>
            <p>Processor understands the restrictions in this Section 2 and will comply with them.</p>
            <p>
                Company, upon written notice, may take reasonable and appropriate steps to stop and remediate
                unauthorized use of Personal Data, including without limitation, exercising Company's right to conduct
                an audit of Processor, or terminating the Principal Agreement and exercising Company's right to request
                deletion or return of Personal Data.
            </p>

            <h4>3. Processor Personnel &amp; Confidentiality</h4>
            <p>
                Processor shall take reasonable steps to ensure the reliability of any personnel who may have access to
                the Company Personal Data, ensuring that all such individuals are subject to confidentiality
                undertakings or professional or statutory obligations of confidentiality with respect to such Company
                Personal Data.
            </p>

            <h4>4. Security</h4>
            <p>
                Taking into account the state of the art, the costs of implementation and the nature, scope, context and
                purposes of Processing as well as the risk of varying likelihood and severity for the rights and
                freedoms of natural persons, Processor shall in relation to the Company Personal Data implement
                appropriate technical and organizational measures to ensure a level of security appropriate to that
                risk, including, as appropriate, the measures referred to in Article 32(1) of the GDPR and UK GDPR.
                These measures include those at Annex II.
            </p>

            <h4>5. Subprocessing</h4>
            <p>
                5.1. The Company provides Processor with general authorization to engage the Subprocessors set out on
                https://posthog.com/subprocessors (the "<strong>Subprocessor Page</strong>"). These will differ
                depending on the Data Center Location chosen by the Company. In addition, Company provides Processor
                with general authorization to engage other third parties as Subprocessors, in accordance with this
                Section 5.
            </p>
            <p>
                5.2. Processor shall enter into a written contract with any Subprocessor and this contract shall impose
                upon the Subprocessor equivalent obligations as imposed by this Agreement upon the Processor. Where the
                Subprocessor fails to fulfil its data protection obligations, Processor shall remain fully liable to the
                Company for the performance of the Subprocessors obligations.
            </p>
            <p>
                5.3. Processor may update the list of Subprocessors from time to time as applicable, providing the
                Company with notice of such update (and an opportunity to object) at least fourteen (14) days in advance
                of such updates.
            </p>
            <p>
                5.4. If the Company objects to a Subprocessor, the Company shall notify Processor thereof in writing
                within seven (7) days after receipt of Processor's updated Subprocessors' list. If the Company objects
                to the use of the Subprocessor, Processor shall use efforts to address the objection through one of the
                following options: (a) Processor will cancel its plans to use Subprocessor with regard to Company
                Personal Data or will offer an alternative to provide the Services without such Subprocessor; or (b)
                Processor will take any corrective steps requested by the Company in its objection (which would
                therefore remove the Company's objection) and proceed to use Subprocessor. If none of the above options
                are reasonably available and the objection has not been sufficiently addressed within thirty (30) days
                after Processor's receipt of the Company's objection, the Company may terminate the affected Service
                with reasonable prior written notice.
            </p>

            <h4>6. Data Subject Rights and Cooperation</h4>
            <p>
                6.1. Taking into account the nature of the Processing, Processor shall assist the Company by
                implementing appropriate technical and organizational measures, insofar as this is possible, for the
                fulfilment of the Company obligations, as reasonably understood by Company, to respond to requests to
                exercise Data Subject rights under applicable Data Protection Laws.
            </p>
            <p>6.2. Processor shall:</p>
            <p>
                (a) notify Company if it receives a request from a Data Subject under any Data Protection Law in respect
                of Company Personal Data; and
            </p>
            <p>
                (b) ensure that it does not respond to that request except on the documented instructions of Company or
                as required by applicable laws to which the Processor is subject.
            </p>
            <p>
                6.3. To the extent required under Data Protection Laws, Processor shall (taking into account the nature
                of the processing and the information available to Processor) provide all reasonably requested
                information regarding the Service to enable the Company to carry out data protection impact assessments
                or prior consultations with data protection authorities and to assist the Company with meeting its
                obligations under Article 32 GDPR/UK GDPR as required by Data Protection Laws.
            </p>
            <p>
                6.4. To the extent that assistance under this Agreement is not included within the Services, the
                Processor may charge a reasonable fee for any such assistance, save where assistance was required
                directly as a result of the Processor's own acts or omissions, in which case such assistance will be at
                the Processor's expense.
            </p>

            <h4>7. Personal Data Breach</h4>
            <p>
                7.1. Processor shall notify Company without undue delay upon Processor becoming aware of a Personal Data
                Breach affecting Company Personal Data, providing Company with sufficient information to allow the
                Company to meet any obligations to report or inform Data Subjects or Supervisory Authorities of the
                Personal Data Breach under applicable Data Protection Laws.
            </p>
            <p>
                7.2. Processor shall cooperate with the Company and take reasonable commercial steps as are directed by
                Company to assist in the investigation, mitigation and remediation of each such Personal Data Breach.
            </p>

            <h4>8. Audits</h4>
            <p>
                The Processor shall make available to the Company all information reasonably necessary to demonstrate
                compliance with this Agreement and at the cost of the Company, allow for and contribute to audits,
                including inspections by the Company in order to assess compliance with this Agreement.
            </p>

            <h4>9. Deletion or return of Company Personal Data</h4>
            <p>
                At the end of the Services, upon the Company's request, Processor shall securely return the Company
                Personal Data or provide a self-service functionality allowing Company to do the same or delete or
                procure the deletion of all copies of the Company Personal Data unless applicable laws require storage
                of such Company or is required to resolve a dispute between the parties or the retention of the Company
                Personal Data is necessary to combat harmful use of the Services.
            </p>

            <h4>10. Data Center Location and Transfers Outside of the Protected Area</h4>
            <p>
                10.1. <strong>Storage of Personal Data.</strong> Company Personal Data will be housed in data centers
                located in the Data Center Location set out in the Principal Agreement unless the parties otherwise
                expressly agree in writing.
            </p>
            <p>
                10.2. <strong>Transfers.</strong> The Company acknowledges that the Processor will Process the Company
                Personal Data outside of the Protected Area including in the US and elsewhere as identified on the
                Subprocessor Page to provide the Services. Company agrees to authorize the transfers to these countries.
            </p>
            <p>
                10.3. <strong>Data Privacy Framework.</strong> Processor confirms that it participates in the EU-US Data
                Privacy Framework, the UK Extension to this Framework and the Swiss-U.S. Data Privacy Framework
                (together, the "<strong>DPF</strong>"). The Supplier undertakes to maintain its self-certification to
                the DPF; to notify Company without undue delay if Processor determines that it will cease to
                self-certify to the DPF; and to notify Company immediately if Processor's participation in the DPF is
                otherwise terminated. In respect of UK Personal Data, Company hereby notifies Processor that Company
                identifies and treats genetic data, data relating to sexual orientation, biometric data processed for
                the purpose of uniquely identifying data subjects and data relating to criminal convictions and offenses
                as sensitive.
            </p>
            <p>
                10.4. <strong>Standard Contractual Clauses:</strong> Notwithstanding 10.3, the parties agree to comply
                with the obligations set out in the Standard Contractual Clauses as though they were set out in full in
                this Agreement, with the Company as the "data exporter" and the Processor as the "data importer", with
                the parties signatures and dating of this Agreement being deemed to be the signature and dating of the
                Standard Contractual Clauses and with Annexes to EU Standard Contractual Clauses and the Appendices to
                the UK Standard Contractual Clauses being as set out in Annex I and II of this Agreement.
            </p>
            <p>10.5. In relation to the EU Standard Contractual Clauses, the Parties agree that:</p>
            <p>
                (a) for the purposes of clause 9, option 2 (general written authorization for subprocessors) shall apply
                and the Parties agree that the time period for notifying changes to the list shall be in accordance with
                Section 5.3 above;
            </p>
            <p>(b) for the purposes of clause 17, the clauses shall be governed by the laws of Ireland;</p>
            <p>(c) for the purposes of clause 18, the courts of Ireland shall have jurisdiction; and</p>
            <p>
                (d) for the purposes of clause 13 and Annex I.C, the competent supervisory authority shall be determined
                in accordance with the GDPR, based on the data exporter's establishment or representative within the
                EEA.
            </p>
            <p>
                10.6. In relation to the UK Standard Contractual Clauses, as permitted by clause 17 of such Addendum,
                the Parties agree to change the format of the information set out in Part 1 of the Addendum so that:
            </p>
            <p>
                (a) the details of the parties in table 1 shall be as set out in Annex I (with no requirement for
                signature);
            </p>
            <p>
                (b) for the purposes of table 2, the Addendum shall be appended to the EU Standard Contractual Clauses
                as defined above (including the selection of modules and options and the disapplication of optional
                clauses as noted in the definition above); and
            </p>
            <p>(c) the appendix information listed in table 3 is set out in Annex I and II.</p>
            <p>
                10.7. In relation to Swiss Personal Data that is transferred outside of the Protected Area, the Parties
                agree that such transfers shall be subject to the EU Standard Contractual Clauses as compiled and
                completed in Sections 10.2 and 10.3 above, with the following amendments: (a) any references to the GDPR
                shall be interpreted as references to the FADP; (b) references to the EU and EU Member States shall be
                interpreted to mean Switzerland; (c) the competent supervisory authority according to Clause 13(a) and
                Part C of Annex I is the FDPIC insofar as the data transfers are governed by the FADP; (d) the term EU
                Member State shall not be interpreted in such a way as to exclude data subject in Switzerland from the
                possibility of suing for their rights in their place of habitual residence in accordance with Clause
                18(c) of the EU Standard Contractual Clauses; and (e) until the entry into force of the revised FADP on
                1 September 2023, the EU Standard Contractual Clauses shall also protect the personal data of legal
                entities and legal entities shall receive the same protection under the EU Standard Contractual Clauses
                as natural persons.
            </p>
            <p>
                10.8. In the event of any conflict between this Agreement and the Standard Contractual Clauses, the
                Standard Contractual Clauses shall prevail.
            </p>
            <p>
                10.9. In the event that a relevant European Commission decision or other valid adequacy method under
                applicable Data Protection Legislation on which the Company has relied in authorizing the data transfer
                is held to be invalid, or that any supervisory authority requires transfers of personal data made
                pursuant to such decision to be suspended, or in the event that Processor ceases to participate in the
                DPF then the parties will agree to use a suitable and appropriate alternative transfer solution.
            </p>

            <h4>11. General Terms</h4>
            <p>
                11.1. <strong>Confidentiality.</strong> Each Party must keep this Agreement and information it receives
                about the other Party and its business in connection with this Agreement ("
                <strong>Confidential Information</strong>") confidential and must not use or disclose that Confidential
                Information without the prior written consent of the other Party except to the extent that:
            </p>
            <p>(a) disclosure is required by law;</p>
            <p>(b) the relevant information is already in the public domain.</p>
            <p>
                11.2. <strong>Notices.</strong> All notices and communications given under this Agreement must be in
                writing and will be delivered personally, sent by post or sent by email to the address or email address
                set out in the heading of this Agreement at such other address as notified from time to time by the
                Parties changing address.
            </p>
            <p>
                11.3. <strong>Governing Law and Jurisdiction.</strong> This Agreement is governed by the laws and choice
                of jurisdiction stipulated in the Principal Agreement.
            </p>
            <p>
                <strong>
                    IN WITNESS WHEREOF, this Agreement is entered into with effect from the date of the last signature
                    set out below.
                </strong>
            </p>

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
                <strong>B. List of Parties.</strong> The data exporter is the Company ({CompanyPlaceholder}) at{' '}
                {AddressPlaceholder}; contact {EmailPlaceholder}; role controller. The data importer is the Processor at
                2261 Market St., #4008, San Francisco, CA 94114, USA; contact person privacy@posthog.com; role
                processor.
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
