# Use a lightweight Node.js image
FROM node:20-slim

# Set the working directory inside the container
WORKDIR /usr/src/app

# Install mcp-remote globally to avoid npx overhead on each run
RUN npm install -g mcp-remote@latest

# Set default environment variable for POSTHOG_REMOTE_MCP_URL
ENV POSTHOG_REMOTE_MCP_URL=https://mcp.posthog.com/mcp

# The entrypoint will run mcp-remote with proper stdio handling
# POSTHOG_AUTH_HEADER should be just the token (e.g., phx_...), we'll add "Bearer " prefix
ENTRYPOINT ["sh", "-c", "mcp-remote \"${POSTHOG_REMOTE_MCP_URL}\" --header \"Authorization:Bearer ${POSTHOG_AUTH_HEADER}\""]
