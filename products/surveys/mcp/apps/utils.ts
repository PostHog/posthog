export const STATUS_VARIANTS: Record<string, 'success' | 'warning' | 'default' | 'info'> = {
    active: 'success',
    draft: 'default',
    completed: 'info',
    archived: 'default',
}

export const SURVEY_TYPE_LABELS: Record<string, string> = {
    popover: 'Popover',
    api: 'API',
    widget: 'Widget',
    external_survey: 'External survey',
}

export const SURVEY_QUESTION_TYPE_LABELS: Record<string, string> = {
    open: 'Open text',
    multiple_choice: 'Multiple choice',
    single_choice: 'Single choice',
    rating: 'Rating',
    link: 'Link',
    nps: 'NPS',
}
