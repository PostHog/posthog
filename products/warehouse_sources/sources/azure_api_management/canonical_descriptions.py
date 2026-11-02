from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_SHARED_COLUMNS = {
    "TimeGenerated": "Date and time when request processing started.",
    "_ItemId": "Unique identifier of the log record.",
    "_ResourceId": "Azure resource ID of the API Management instance that wrote the record.",
    "_SubscriptionId": "Azure subscription that the API Management instance belongs to.",
    "TenantId": "ID of the Log Analytics workspace that stores the record.",
    "Region": "Azure region of the API Management gateway that handled the request.",
    "CorrelationId": "ID that groups the records written for one request.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "ApiManagementGatewayLogs": {
        "description": "One row per request that passed through the API Management gateway, with timings, response codes, and the API, operation, product, and subscription it matched.",
        "docs_url": "https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/apimanagementgatewaylogs",
        "columns": {
            **_SHARED_COLUMNS,
            "ApiId": "ID of the API the request matched.",
            "OperationId": "ID of the API operation the request matched.",
            "ProductId": "ID of the product the calling subscription belongs to.",
            "ApimSubscriptionId": "ID of the API Management subscription key the caller used.",
            "UserId": "ID of the API Management user that owns the subscription.",
            "Method": "HTTP method of the client request.",
            "Url": "URL of the client request.",
            "ResponseCode": "HTTP status code the gateway returned to the client.",
            "BackendResponseCode": "HTTP status code the backend returned to the gateway.",
            "TotalTime": "Time in milliseconds from the first byte the gateway received to the last byte it sent.",
            "BackendTime": "Time in milliseconds the gateway spent waiting for the backend.",
            "CallerIpAddress": "IP address of the client that called the gateway.",
            "IsRequestSuccess": "Whether the request completed with a success status code.",
            "LastErrorReason": "Reason of the last error that occurred while the gateway processed the request.",
            "LastErrorMessage": "Message of the last error that occurred while the gateway processed the request.",
            "RequestBody": "Client request body, when body logging is turned on.",
            "ResponseBody": "Gateway response body, when body logging is turned on.",
        },
    },
    "ApiManagementGatewayLlmLog": {
        "description": "One row per language model request that passed through the API Management AI gateway, with token counts and the model used.",
        "docs_url": "https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/apimanagementgatewayllmlog",
        "columns": {
            **_SHARED_COLUMNS,
            "CorrelationId": "ID that matches the CorrelationId of the same request in ApiManagementGatewayLogs.",
            "ModelName": "Model name used by the request.",
            "DeploymentName": "Deployment name used by the client.",
            "ApiVersion": "API version used by the client.",
            "PromptTokens": "Number of prompt tokens used by the request.",
            "CompletionTokens": "Number of completion tokens used by the request.",
            "TotalTokens": "Total number of tokens used by the request.",
            "IsStreamCompletion": "Whether the request asked for a streamed response.",
            "RequestId": "Request ID that the language model returned.",
            "RequestMessages": "Contents of the request messages.",
            "ResponseMessages": "Contents of the response messages.",
            "SequenceNumber": "Index of this entry in the message exchange.",
        },
    },
    "ApiManagementWebSocketConnectionLogs": {
        "description": "One row per WebSocket connection event that passed through the API Management gateway.",
        "docs_url": "https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/apimanagementwebsocketconnectionlogs",
        "columns": {
            **_SHARED_COLUMNS,
            "CorrelationId": "ID that groups the events of one WebSocket request.",
            "EventName": "Name of the event that describes the operation.",
            "Source": "Source of the request or message for the WebSocket connection.",
            "Destination": "Destination of the request or message for the WebSocket connection.",
            "Error": "Error details for the WebSocket connection, if any.",
        },
    },
}
