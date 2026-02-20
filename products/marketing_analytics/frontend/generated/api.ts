/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 * 
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator';

export const getMarketingAnalyticsTestMappingCreateUrl = (projectId: string,) => {


  

  return `/api/environments/${projectId}/marketing_analytics/test_mapping/`
}

export const marketingAnalyticsTestMappingCreate = async (projectId: string, options?: RequestInit): Promise<void> => {
  
  return apiMutator<void>(getMarketingAnalyticsTestMappingCreateUrl(projectId),
  {      
    ...options,
    method: 'POST'
    
    
  }
);}



