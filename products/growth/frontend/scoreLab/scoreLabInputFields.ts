// Mirrors HARMONIC_INPUT_FIELD_CHOICES in products/growth/backend/enrichment/lab.py. The score
// lab API accepts any dotted path as input_fields (serializers.ListField(child=CharField())), so
// there's no generated enum to derive this from — keep this list in sync with the backend by hand
// until that choice list is exposed through the OpenAPI schema.
export interface ScoreLabInputFieldOption {
    value: string
    label: string
}

export const SCORE_LAB_INPUT_FIELD_OPTIONS: ScoreLabInputFieldOption[] = [
    { value: 'name', label: 'Company name' },
    { value: 'description', label: 'Description' },
    { value: 'website.url', label: 'Website URL' },
    { value: 'companyType', label: 'Company type' },
    { value: 'headcount', label: 'Headcount' },
    { value: 'tagsV2', label: 'Tags (tagsV2)' },
    { value: 'funding.fundingStage', label: 'Funding stage' },
    { value: 'funding.fundingTotal', label: 'Total funding' },
    { value: 'funding.lastFundingAt', label: 'Last funding date' },
    { value: 'funding.investors', label: 'Investors' },
    { value: 'location.country', label: 'Country' },
    { value: 'foundingDate.date', label: 'Founding date' },
]
