ENDPOINTS = {
    "projects": "project",
    "experiments": "experiment",
    "datasets": "dataset",
    "prompts": "prompt",
    "functions": "function",
}

PAGE_SIZE = 100

AUTH_ERRORS = {
    401: "Braintrust rejected the API key. Check the key in your organization settings.",
    403: "The Braintrust API key cannot read this resource. Check its permissions and the API URL.",
}
