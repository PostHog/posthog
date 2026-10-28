import type {
    ScoutRubricReferenceContextApi,
    ScoutRubricReferenceContextDocumentApi,
} from 'products/signals/frontend/generated/api.schemas'

export const scoutRubricReferenceFixture = {
    schema_version: 1,
    skill_id: '00000000-0000-4000-8000-000000000031',
    skill_name: 'signals-scout-example',
    skill_version: 3,
    description: 'Compare product activity across equivalent time windows.',
    instructions: 'Compare the last seven days with the preceding seven days. Cite the counts behind each change.',
    instructions_truncated: false,
    report_channel: 'emit',
    report_disposition_instructions: 'Explain the evidence and a useful next step in each report.',
    reference_files: [],
    reference_files_truncated: false,
    reference_texts: [],
    reference_limits: { omitted_files: 0, truncated_files: [] },
} satisfies ScoutRubricReferenceContextApi & ScoutRubricReferenceContextDocumentApi
