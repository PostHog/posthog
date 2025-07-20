import { kea, path, actions, reducers, selectors, listeners } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import type { githubIntegrationLogicType } from './githubIntegrationLogicType'

export interface GitHubIntegration {
    id?: number
    repo_url: string
    repo_owner: string
    repo_name: string
    default_branch: string
    branch_prefix: string
    auto_create_pr: boolean
    github_token: string
    github_app_installation_id?: string
    is_active: boolean
    created_at?: string
    updated_at?: string
}

export interface GitHubIntegrationStatus {
    configured: boolean
    active: boolean
    repository: string | null
    has_token: boolean
    auto_create_pr: boolean
}

export interface GitHubTestResult {
    success: boolean
    message?: string
    error?: string
    repository?: {
        name: string
        default_branch: string
        private: boolean
        url: string
    }
}

export interface GitHubIntegrationLogicProps {
    teamId: number
}

export const githubIntegrationLogic = kea<githubIntegrationLogicType>([
    path(['products', 'issue_tracker', 'frontend', 'logic', 'githubIntegrationLogic']),
    
    actions({
        setFormValue: (field: keyof GitHubIntegration, value: any) => ({ field, value }),
        resetForm: true,
        testConnection: (integrationId: number) => ({ integrationId }),
        clearTestResult: true,
    }),

    loaders(({ props, values }) => ({
        integrationStatus: {
            __default: null as GitHubIntegrationStatus | null,
            loadIntegrationStatus: async () => {
                const response = await api.get(`api/environments/${props.teamId}/github-integration/status/`)
                return response
            },
        },
        integration: {
            __default: null as GitHubIntegration | null,
            loadIntegration: async () => {
                try {
                    const response = await api.get(`api/environments/${props.teamId}/github-integration/`)
                    return response.results?.[0] || null
                } catch (error) {
                    return null
                }
            },
            createOrUpdateIntegration: async (data: Partial<GitHubIntegration>) => {
                try {
                    let response
                    
                    // Always check if integration exists first
                    const existingIntegration = values.integration || 
                        await api.get(`api/environments/${props.teamId}/github-integration/`).then(res => res.results?.[0]).catch(() => null)
                    
                    if (existingIntegration?.id) {
                        // Update existing integration
                        response = await api.update(`api/environments/${props.teamId}/github-integration/${existingIntegration.id}/`, data)
                        lemonToast.success('GitHub integration updated successfully')
                    } else {
                        // Create new integration
                        response = await api.create(`api/environments/${props.teamId}/github-integration/`, data)
                        lemonToast.success('GitHub integration created successfully')
                    }
                    
                    // Reload status and integration after save - wrap in try/catch to avoid double error toasts
                    try {
                        await Promise.all([
                            actions.loadIntegrationStatus(),
                            actions.loadIntegration()
                        ])
                    } catch (reloadError) {
                        console.warn('Failed to reload integration data after save:', reloadError)
                        // Don't show another error toast since the save succeeded
                    }
                    
                    return response
                } catch (error) {
                    lemonToast.error('Failed to save GitHub integration')
                    throw error
                }
            },
        },
        testResult: {
            __default: null as GitHubTestResult | null,
            testConnection: async ({ integrationId }) => {
                try {
                    const response = await api.create(`api/environments/${props.teamId}/github-integration/${integrationId}/test_connection/`)
                    if (response.success) {
                        lemonToast.success('GitHub connection test successful')
                    } else {
                        lemonToast.error(`Connection test failed: ${response.error}`)
                    }
                    return response
                } catch (error) {
                    const errorMsg = 'Connection test failed'
                    lemonToast.error(errorMsg)
                    return {
                        success: false,
                        error: errorMsg,
                    }
                }
            },
        },
    })),

    reducers({
        formValues: [
            {} as Partial<GitHubIntegration>,
            {
                setFormValue: (state, { field, value }) => ({
                    ...state,
                    [field]: value,
                    // Auto-populate owner/repo from URL if repo_url is being set
                    ...(field === 'repo_url' && value
                        ? (() => {
                              const match = value.match(/https:\/\/github\.com\/([^\/]+)\/([^\/]+?)(?:\.git)?(?:\/)?$/)
                              if (match) {
                                  return {
                                      repo_owner: match[1],
                                      repo_name: match[2],
                                  }
                              }
                              return {}
                          })()
                        : {}),
                }),
                resetForm: (state) => ({ ...values.integration }),
                loadIntegrationSuccess: (state, { integration }) => ({ ...integration }),
            },
        ],
    }),

    selectors({
        isSaving: [
            (s) => [s.integrationLoading],
            (integrationLoading) => integrationLoading,
        ],
        isTesting: [
            (s) => [s.testResultLoading],
            (testResultLoading) => testResultLoading,
        ],
        isLoading: [
            (s) => [s.integrationStatusLoading, s.integrationLoading],
            (statusLoading, integrationLoading) => statusLoading || integrationLoading,
        ],
    }),

    listeners(({ actions, values }) => ({
        loadIntegrationStatusSuccess: () => {
            // Load the full integration details if one exists
            if (values.integrationStatus?.configured) {
                actions.loadIntegration()
            }
        },
        loadIntegrationSuccess: () => {
            // Initialize form with loaded integration data
            if (values.integration) {
                actions.resetForm()
            }
        },
        createOrUpdateIntegrationSuccess: () => {
            // Clear test result on successful save
            actions.clearTestResult()
        },
        clearTestResult: () => {
            // This will be handled by the loader reset
        },
    })),
])