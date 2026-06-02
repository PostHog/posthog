// source `mcp` — proxies an in-cluster MCP server via the streamable
// HTTP transport (the v1 transport in the MCP spec for over-the-wire
// servers). Stdio transport is intentionally deferred — most production
// MCPs are deployed as their own service inside the customer's cluster,
// and the reference runner forwards to them.
//
// Behaviour:
//   - At construction, connect to the upstream and call `initialize`.
//   - Cache the result of `listTools()` once, since `Tools()` is called
//     on every runner heartbeat and we don't want to hammer the upstream.
//   - On `Call`, forward to `callTool` with the runner-provided context.
//     ctx cancellation propagates to the upstream call.
//
// The MCP source publishes tools under qualified names — e.g. a tool
// named `query_loki` in a source named `grafana` is published as
// `grafana.query_loki`. The runner's catalog uses the qualified form,
// and `Call(toolName, ...)` is dispatched here with the qualified name —
// we strip the source prefix before forwarding to the upstream MCP.
package sources

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"sync"

	"github.com/mark3labs/mcp-go/client"
	"github.com/mark3labs/mcp-go/mcp"

	"github.com/posthog/posthog/services/agent-tool-runner/protocol"
)

// MCPSource is a connected MCP-over-HTTP client with a cached tool catalog.
type MCPSource struct {
	name     string
	endpoint string

	clientMu sync.Mutex
	client   *client.Client // nil until Connect() succeeds

	catalogMu sync.RWMutex
	catalog   []protocol.ToolDescriptor // computed once after Connect()
}

// NewMCPSource constructs the source. It does NOT open the connection —
// the caller must invoke Connect() once before Tools() / Call(). This
// split lets the runner wire all sources at startup and surface
// connection errors deterministically rather than lazily on first use.
func NewMCPSource(name, endpoint string) (*MCPSource, error) {
	if name == "" {
		return nil, errors.New("mcp source: name is required")
	}
	if endpoint == "" {
		return nil, errors.New("mcp source: endpoint is required")
	}
	return &MCPSource{name: name, endpoint: endpoint}, nil
}

// Connect opens the MCP client, sends `initialize`, and primes the tool
// catalog cache. Idempotent — calling Connect twice is a no-op on the
// second call.
func (s *MCPSource) Connect(ctx context.Context) error {
	s.clientMu.Lock()
	defer s.clientMu.Unlock()
	if s.client != nil {
		return nil
	}

	c, err := client.NewStreamableHttpClient(s.endpoint)
	if err != nil {
		return fmt.Errorf("mcp source %q: open client: %w", s.name, err)
	}
	if err := c.Start(ctx); err != nil {
		return fmt.Errorf("mcp source %q: start client: %w", s.name, err)
	}

	initReq := mcp.InitializeRequest{}
	initReq.Params.ProtocolVersion = mcp.LATEST_PROTOCOL_VERSION
	initReq.Params.ClientInfo = mcp.Implementation{
		Name:    "posthog-tool-runner",
		Version: "1",
	}
	if _, err := c.Initialize(ctx, initReq); err != nil {
		_ = c.Close()
		return fmt.Errorf("mcp source %q: initialize: %w", s.name, err)
	}

	listResp, err := c.ListTools(ctx, mcp.ListToolsRequest{})
	if err != nil {
		_ = c.Close()
		return fmt.Errorf("mcp source %q: list tools: %w", s.name, err)
	}

	catalog := make([]protocol.ToolDescriptor, 0, len(listResp.Tools))
	for _, tool := range listResp.Tools {
		schema, err := json.Marshal(tool.InputSchema)
		if err != nil {
			_ = c.Close()
			return fmt.Errorf(
				"mcp source %q: marshal schema for tool %q: %w",
				s.name, tool.Name, err,
			)
		}
		catalog = append(catalog, protocol.ToolDescriptor{
			Name:        s.name + "." + tool.Name,
			Description: tool.Description,
			InputSchema: schema,
		})
	}

	s.client = c
	s.setCatalog(catalog)
	return nil
}

// Close shuts down the underlying MCP client. Safe to call multiple times.
func (s *MCPSource) Close() error {
	s.clientMu.Lock()
	defer s.clientMu.Unlock()
	if s.client == nil {
		return nil
	}
	err := s.client.Close()
	s.client = nil
	return err
}

func (s *MCPSource) setCatalog(c []protocol.ToolDescriptor) {
	s.catalogMu.Lock()
	defer s.catalogMu.Unlock()
	s.catalog = c
}

// Tools returns the cached catalog. Connect() must have been called first;
// before that the catalog is empty.
func (s *MCPSource) Tools() []protocol.ToolDescriptor {
	s.catalogMu.RLock()
	defer s.catalogMu.RUnlock()
	out := make([]protocol.ToolDescriptor, len(s.catalog))
	copy(out, s.catalog)
	return out
}

// Call forwards an invocation to the upstream MCP server. toolName is the
// qualified form (`<source>.<tool>`) — we strip the prefix before sending.
func (s *MCPSource) Call(ctx context.Context, toolName string, args json.RawMessage) (json.RawMessage, error) {
	s.clientMu.Lock()
	c := s.client
	s.clientMu.Unlock()
	if c == nil {
		return nil, fmt.Errorf("mcp source %q: not connected", s.name)
	}

	bareName, ok := strings.CutPrefix(toolName, s.name+".")
	if !ok {
		return nil, fmt.Errorf("mcp source %q: tool name %q not prefixed with source", s.name, toolName)
	}

	var argMap map[string]any
	if len(args) > 0 {
		if err := json.Unmarshal(args, &argMap); err != nil {
			return nil, fmt.Errorf("mcp source %q: unmarshal args: %w", s.name, err)
		}
	}
	req := mcp.CallToolRequest{}
	req.Params.Name = bareName
	req.Params.Arguments = argMap

	resp, err := c.CallTool(ctx, req)
	if err != nil {
		return nil, fmt.Errorf("mcp source %q: call tool %q: %w", s.name, bareName, err)
	}
	if resp.IsError {
		// The MCP server reported an in-band error. Surface it to the
		// agent as a tool-call failure rather than a runner error.
		return nil, fmt.Errorf("mcp source %q: tool %q returned error: %s", s.name, bareName, mcpResultText(resp))
	}

	// Re-marshal the response content as JSON. The MCP `Result` shape is
	// `{ content: [...]; isError: bool }` — we pass it through verbatim so
	// the agent receives whatever the upstream MCP intended.
	encoded, err := json.Marshal(resp)
	if err != nil {
		return nil, fmt.Errorf("mcp source %q: marshal response: %w", s.name, err)
	}
	return encoded, nil
}

// mcpResultText extracts whatever text content is present in the response —
// best-effort, only used for the error path.
func mcpResultText(resp *mcp.CallToolResult) string {
	var sb strings.Builder
	for _, c := range resp.Content {
		if tc, ok := c.(mcp.TextContent); ok {
			sb.WriteString(tc.Text)
			sb.WriteByte(' ')
		}
	}
	return strings.TrimSpace(sb.String())
}
