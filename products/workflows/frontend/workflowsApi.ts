import * as generated from './generated/api'

type GeneratedApiAdapter = (...args: any[]) => Promise<any>

export const hogFlowTemplatesCreate = generated.hogFlowTemplatesCreate as GeneratedApiAdapter
export const hogFlowTemplatesDestroy = generated.hogFlowTemplatesDestroy as GeneratedApiAdapter
export const hogFlowTemplatesList = generated.hogFlowTemplatesList as GeneratedApiAdapter
export const hogFlowTemplatesPartialUpdate = generated.hogFlowTemplatesPartialUpdate as GeneratedApiAdapter
export const hogFlowTemplatesRetrieve = generated.hogFlowTemplatesRetrieve as GeneratedApiAdapter
export const hogFlowsBatchJobsCreate = generated.hogFlowsBatchJobsCreate as GeneratedApiAdapter
export const hogFlowsBatchJobsList = generated.hogFlowsBatchJobsList as GeneratedApiAdapter
export const hogFlowsBulkDeleteCreate = generated.hogFlowsBulkDeleteCreate as GeneratedApiAdapter
export const hogFlowsCreate = generated.hogFlowsCreate as GeneratedApiAdapter
export const hogFlowsDestroy = generated.hogFlowsDestroy as GeneratedApiAdapter
export const hogFlowsDiscardDraftCreate = generated.hogFlowsDiscardDraftCreate as GeneratedApiAdapter
export const hogFlowsList = generated.hogFlowsList as GeneratedApiAdapter
export const hogFlowsPartialUpdate = generated.hogFlowsPartialUpdate as GeneratedApiAdapter
export const hogFlowsPublishCreate = generated.hogFlowsPublishCreate as GeneratedApiAdapter
export const hogFlowsRetrieve = generated.hogFlowsRetrieve as GeneratedApiAdapter
export const hogFlowsSchedulesCreate = generated.hogFlowsSchedulesCreate as GeneratedApiAdapter
export const hogFlowsSchedulesDestroy = generated.hogFlowsSchedulesDestroy as GeneratedApiAdapter
export const hogFlowsSchedulesList = generated.hogFlowsSchedulesList as GeneratedApiAdapter
export const hogFlowsSchedulesPartialUpdate = generated.hogFlowsSchedulesPartialUpdate as GeneratedApiAdapter
export const hogFlowsUserBlastRadiusCreate = generated.hogFlowsUserBlastRadiusCreate as GeneratedApiAdapter
