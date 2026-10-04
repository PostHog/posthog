import type {
    EmailBrandApi,
    EmailBrandCandidateApi,
    EmailBrandDetectionApi,
    RepositorySuggestionsApi,
} from '../generated/api.schemas'

export const exampleSuggestions: RepositorySuggestionsApi = {
    integration_id: 7,
    repositories: [
        {
            id: 11,
            name: 'juniper-web',
            full_name: 'example/juniper-web',
            language: 'TypeScript',
            pushed_at: null,
            reasons: ['name_match', 'web_language'],
        },
    ],
}

const candidate = (value: string, path: string, line: number): EmailBrandCandidateApi => ({
    value,
    path,
    line,
    default_theme: false,
    font_stack: null,
})

export const exampleDetection: EmailBrandDetectionApi = {
    repository: 'example/juniper-web',
    app_root: '',
    app_root_alternatives: [],
    proposal: {
        name: candidate('Juniper', 'public/manifest.json', 2),
        primary_color: candidate('#276749', 'src/theme.css', 4),
        accent_color: candidate('#d69e2e', 'src/theme.css', 5),
        text_color: candidate('#111111', 'src/theme.css', 6),
        background_color: candidate('#ffffff', 'src/theme.css', 7),
        font_family: { ...candidate('Inter', 'src/theme.css', 8), font_stack: 'Inter, Arial, Helvetica, sans-serif' },
    },
    candidates: {
        name: [],
        primary_color: [],
        accent_color: [],
        text_color: [],
        background_color: [],
        font_family: [],
    },
    logo_candidates: [],
    files_read: [
        { path: 'public/manifest.json', found: [{ field: 'name', value: 'Juniper' }] },
        {
            path: 'src/theme.css',
            found: [
                { field: 'primary_color', value: '#276749' },
                { field: 'font_family', value: 'Inter' },
            ],
        },
    ],
}

export const exampleBrand: EmailBrandApi = {
    id: '00000000-0000-4000-8000-000000000209',
    name: 'Juniper',
    logo: null,
    logo_url: null,
    primary_color: '#276749',
    accent_color: '#d69e2e',
    text_color: '#111111',
    background_color: '#ffffff',
    font_family: 'Inter',
    font_stack: 'Inter, Arial, Helvetica, sans-serif',
    source_repository: 'example/juniper-web',
    app_root: '',
    sources: {
        name: { path: 'public/manifest.json', line: 2, detected_value: 'Juniper' },
        primary_color: { path: 'src/theme.css', line: 4, detected_value: '#276749' },
    },
    edited: {
        name: false,
        logo: false,
        primary_color: false,
        accent_color: false,
        text_color: false,
        background_color: false,
        font_family: false,
    },
    created_at: '2026-10-03T00:00:00Z',
    updated_at: '2026-10-03T00:00:00Z',
}
