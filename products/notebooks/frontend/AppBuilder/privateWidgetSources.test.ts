import { privateWidgetSourceNames } from './privateWidgetSources'

describe('privateWidgetSourceNames', () => {
    it('keeps native SQL on the filtered frame route and privately runs downstream Python and connected SQL', () => {
        const markdown = [
            '<SQLV2 nodeId="n" returnVariable="native_rows" code="SELECT 1 AS count" />',
            '<PythonV2 nodeId="p" returnVariable="calculated" code="calculated = native_rows.copy()" />',
            '<SQLV2 nodeId="d" returnVariable="report" code="SELECT * FROM calculated" />',
            '<SQLV2 nodeId="c" returnVariable="external" connectionId="sample" code="SELECT 1 AS value" />',
        ].join('\n\n')
        expect([...privateWidgetSourceNames(markdown)].sort()).toEqual(['calculated', 'external', 'report'])
    })
})
