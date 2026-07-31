/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { MCPFeedbackCreateApi, MCPMissingCapabilityCreateApi } from './api.zod.schemas'

/**
 * Create a new MCP feedback submission for the current project.
 */
export const McpAnalyticsFeedbackCreateBody = MCPFeedbackCreateApi

/**
 * Create a new missing capability report for the current project.
 */
export const McpAnalyticsMissingCapabilitiesCreateBody = MCPMissingCapabilityCreateApi
