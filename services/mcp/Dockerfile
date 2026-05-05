# Track the repo's Node baseline (.nvmrc). Node 20 is past Maintenance LTS EOL (2026-04-30).
FROM node:24.13.0-bookworm-slim

# Set the working directory inside the container
WORKDIR /usr/src/app

# Pin mcp-remote so two `docker build` invocations produce the same image.
# Bump deliberately when upstream ships a fix; do not float `@latest` into a baked image.
RUN npm install -g mcp-remote@0.1.38

# Set default environment variable for POSTHOG_REMOTE_MCP_URL
ENV POSTHOG_REMOTE_MCP_URL=https://mcp.posthog.com/mcp

USER node

# The entrypoint will run mcp-remote with proper stdio handling
# POSTHOG_AUTH_HEADER should be just the token (e.g., phx_...), we'll add "Bearer " prefix
ENTRYPOINT ["sh", "-c", "mcp-remote \"${POSTHOG_REMOTE_MCP_URL}\" --header \"Authorization:Bearer ${POSTHOG_AUTH_HEADER}\""]
