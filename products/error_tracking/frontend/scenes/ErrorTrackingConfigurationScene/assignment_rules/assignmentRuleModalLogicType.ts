// This file is manually maintained because kea-typegen cannot parse factory-built logics.

import type { Logic } from 'kea'

import type { ErrorTrackingAssignmentRule } from '../rules/types'

export interface assignmentRuleModalLogicType extends Logic {
    actionCreators: {
        openModal: (rule?: ErrorTrackingAssignmentRule) => { type: string; payload: { rule: ErrorTrackingAssignmentRule | null } }
        closeModal: () => { type: string; payload: true }
        updateRule: (rule: ErrorTrackingAssignmentRule) => { type: string; payload: { rule: ErrorTrackingAssignmentRule } }
        increaseDateRange: () => { type: string; payload: true }
        loadMatchCount: () => { type: string; payload: any }
        loadMatchCountSuccess: (matchResult: { exceptionCount: number; issueCount: number } | null) => { type: string; payload: { matchResult: { exceptionCount: number; issueCount: number } | null } }
        loadMatchCountFailure: (error: string) => { type: string; payload: { error: string } }
        resetMatchCount: () => { type: string; payload: any }
        saveRule: () => { type: string; payload: any }
        saveRuleSuccess: (saving: boolean) => { type: string; payload: { saving: boolean } }
        saveRuleFailure: (error: string) => { type: string; payload: { error: string } }
        deleteRule: () => { type: string; payload: any }
        deleteRuleSuccess: (deleting: boolean) => { type: string; payload: { deleting: boolean } }
        deleteRuleFailure: (error: string) => { type: string; payload: { error: string } }
    }
    actionKeys: Record<string, string>
    actionTypes: {
        openModal: string
        closeModal: string
        updateRule: string
        increaseDateRange: string
        loadMatchCount: string
        loadMatchCountSuccess: string
        loadMatchCountFailure: string
        resetMatchCount: string
        saveRule: string
        saveRuleSuccess: string
        saveRuleFailure: string
        deleteRule: string
        deleteRuleSuccess: string
        deleteRuleFailure: string
    }
    actions: {
        openModal: (rule?: ErrorTrackingAssignmentRule) => void
        closeModal: () => void
        updateRule: (rule: ErrorTrackingAssignmentRule) => void
        increaseDateRange: () => void
        loadMatchCount: () => void
        loadMatchCountSuccess: (matchResult: { exceptionCount: number; issueCount: number } | null) => void
        loadMatchCountFailure: (error: string) => void
        resetMatchCount: () => void
        saveRule: () => void
        saveRuleSuccess: (saving: boolean) => void
        saveRuleFailure: (error: string) => void
        deleteRule: () => void
        deleteRuleSuccess: (deleting: boolean) => void
        deleteRuleFailure: (error: string) => void
    }
    asyncActions: assignmentRuleModalLogicType['actions']
    defaults: {
        isOpen: boolean
        rule: ErrorTrackingAssignmentRule
        dateRange: string
        matchResult: { exceptionCount: number; issueCount: number } | null
        matchResultLoading: boolean
        saving: boolean
        savingLoading: boolean
        deleting: boolean
        deletingLoading: boolean
    }
    events: {}
    key: undefined
    listeners: {}
    path: ['products', 'error_tracking', 'scenes', 'ErrorTrackingConfigurationScene', 'assignment_rules', 'assignmentRuleModalLogic']
    pathString: 'products.error_tracking.scenes.ErrorTrackingConfigurationScene.assignment_rules.assignmentRuleModalLogic'
    props: Record<string, unknown>
    reducer: (state: any, action: any, fullState: any) => assignmentRuleModalLogicType['defaults']
    reducers: {
        isOpen: (state: boolean, action: any, fullState: any) => boolean
        rule: (state: ErrorTrackingAssignmentRule, action: any, fullState: any) => ErrorTrackingAssignmentRule
        dateRange: (state: string, action: any, fullState: any) => string
        matchResult: (state: { exceptionCount: number; issueCount: number } | null, action: any, fullState: any) => { exceptionCount: number; issueCount: number } | null
        matchResultLoading: (state: boolean, action: any, fullState: any) => boolean
        saving: (state: boolean, action: any, fullState: any) => boolean
        savingLoading: (state: boolean, action: any, fullState: any) => boolean
        deleting: (state: boolean, action: any, fullState: any) => boolean
        deletingLoading: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (state: any) => assignmentRuleModalLogicType['defaults']
    selectors: {
        isOpen: (state: any, props?: any) => boolean
        rule: (state: any, props?: any) => ErrorTrackingAssignmentRule
        dateRange: (state: any, props?: any) => string
        matchResult: (state: any, props?: any) => { exceptionCount: number; issueCount: number } | null
        matchResultLoading: (state: any, props?: any) => boolean
        saving: (state: any, props?: any) => boolean
        savingLoading: (state: any, props?: any) => boolean
        deleting: (state: any, props?: any) => boolean
        deletingLoading: (state: any, props?: any) => boolean
        hasFilters: (state: any, props?: any) => boolean
        hasAssignee: (state: any, props?: any) => boolean
    }
    sharedListeners: {}
    values: {
        isOpen: boolean
        rule: ErrorTrackingAssignmentRule
        dateRange: string
        matchResult: { exceptionCount: number; issueCount: number } | null
        matchResultLoading: boolean
        saving: boolean
        savingLoading: boolean
        deleting: boolean
        deletingLoading: boolean
        hasFilters: boolean
        hasAssignee: boolean
    }
    _isKea: true
    _isKeaWithKey: false
}
