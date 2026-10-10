import { allOperatorsMapping, chooseOperatorMap, isOperatorDate, isOperatorMulti } from 'lib/utils/operators'

import { PropertyOperator } from '~/types'
import type { PropertyFilterValue, PropertyType } from '~/types'

export type FilterValueKind = 'none' | 'one' | 'many'

export interface FilterOperatorOption {
    value: PropertyOperator
    label: string
}

const NO_VALUE_OPERATORS: PropertyOperator[] = [PropertyOperator.IsSet, PropertyOperator.IsNotSet]

export function filterOperatorOptions(
    propertyType: PropertyType | undefined,
    currentOperator: PropertyOperator
): FilterOperatorOption[] {
    const operatorNames = chooseOperatorMap(propertyType)
    const operators = Object.keys(operatorNames) as PropertyOperator[]
    if (!operators.includes(currentOperator)) {
        operators.push(currentOperator)
    }
    return operators.map((operator) => ({
        value: operator,
        // The app's operator names start with a symbol, such as "= equals".
        label: (operatorNames[operator] ?? allOperatorsMapping[operator] ?? operator.replace(/_/g, ' ')).replace(
            /^[^\p{L}\p{N}]+\s+/u,
            ''
        ),
    }))
}

export function defaultFilterOperator(propertyType: PropertyType | undefined): PropertyOperator {
    const operators = Object.keys(chooseOperatorMap(propertyType)) as PropertyOperator[]
    return operators.includes(PropertyOperator.Exact) ? PropertyOperator.Exact : operators[0]
}

export function filterValueKind(operator: PropertyOperator, value?: PropertyFilterValue): FilterValueKind {
    if (NO_VALUE_OPERATORS.includes(operator)) {
        return 'none'
    }
    return isOperatorMulti(operator) || (Array.isArray(value) && value.length > 1) ? 'many' : 'one'
}

export function filterValueList(value: PropertyFilterValue | undefined): string[] {
    if (value === null || value === undefined || value === '') {
        return []
    }
    return (Array.isArray(value) ? value : [value]).map(String)
}

export function valueForOperator(
    operator: PropertyOperator,
    previousOperator: PropertyOperator,
    previousValue: PropertyFilterValue | undefined
): PropertyFilterValue {
    const kind = filterValueKind(operator)
    if (kind === 'none') {
        // The app stores the operator name as the value of "is set" and "is not set".
        return operator
    }
    const keepsValue =
        filterValueKind(previousOperator) !== 'none' && isOperatorDate(operator) === isOperatorDate(previousOperator)
    const values = keepsValue ? filterValueList(previousValue) : []
    if (kind === 'many') {
        return values
    }
    return isOperatorMulti(previousOperator) || values.length <= 1 ? (values[0] ?? '') : values
}
