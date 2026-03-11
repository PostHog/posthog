export const STATUS_VARIANTS: Record<string, 'success' | 'warning' | 'neutral' | 'info'> = {
    active: 'success',
    draft: 'neutral',
    completed: 'info',
    archived: 'neutral',
}

export const TYPE_LABELS: Record<string, string> = {
    open: 'Open text',
    multiple_choice: 'Multiple choice',
    single_choice: 'Single choice',
    rating: 'Rating',
    link: 'Link',
    nps: 'NPS',
}
