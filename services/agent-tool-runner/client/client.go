// Package client is the runner's HTTP client to the PostHog ingress.
// Every method maps 1:1 to an endpoint documented in the plan:
//
//   - Heartbeat       — POST /runners/heartbeat
//   - Poll            — GET  /runners/poll?max_wait_seconds=N
//   - PostResult      — POST /runners/invocations/:id/result
//   - ExtendLease     — POST /runners/invocations/:id/extend_lease
package client

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"time"

	"github.com/posthog/posthog/services/agent-tool-runner/protocol"
)

// Client is bound to one (endpoint, token) pair — i.e. one project. The
// runner spawns one Client per ProjectConfig.
type Client struct {
	endpoint string
	token    string
	http     *http.Client
}

// Options configures a Client. Endpoint and Token are required.
type Options struct {
	Endpoint   string
	Token      string
	HTTPClient *http.Client
}

// New constructs a Client. If HTTPClient is nil a default http.Client with
// no overall timeout is used — long-poll relies on per-request context
// timeouts, not the transport's deadline.
func New(opts Options) (*Client, error) {
	if opts.Endpoint == "" {
		return nil, errors.New("client: endpoint is required")
	}
	if opts.Token == "" {
		return nil, errors.New("client: token is required")
	}
	httpClient := opts.HTTPClient
	if httpClient == nil {
		httpClient = &http.Client{}
	}
	return &Client{endpoint: opts.Endpoint, token: opts.Token, http: httpClient}, nil
}

// Heartbeat reports liveness and replaces the runner's tool catalog. The
// runner calls this once at boot (to register) and then on a fixed
// interval thereafter.
func (c *Client) Heartbeat(ctx context.Context, req protocol.HeartbeatRequest) (*protocol.HeartbeatResponse, error) {
	var resp protocol.HeartbeatResponse
	if err := c.doJSON(ctx, http.MethodPost, "/runners/heartbeat", req, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

// Poll long-polls for the next leased invocation. Returns (nil, nil) if
// the long-poll window elapsed with no work — the caller should re-poll
// immediately. The context controls the overall poll deadline; the
// `maxWait` parameter is forwarded to the server as a hint.
func (c *Client) Poll(ctx context.Context, maxWait time.Duration) (*protocol.LeasedInvocation, error) {
	path := "/runners/poll?max_wait_seconds=" + strconv.Itoa(int(maxWait.Seconds()))
	httpReq, err := c.newRequest(ctx, http.MethodGet, path, nil)
	if err != nil {
		return nil, err
	}
	httpResp, err := c.http.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("poll: %w", err)
	}
	defer httpResp.Body.Close()

	switch httpResp.StatusCode {
	case http.StatusNoContent:
		return nil, nil
	case http.StatusOK:
		var resp protocol.PollResponse
		if err := json.NewDecoder(httpResp.Body).Decode(&resp); err != nil {
			return nil, fmt.Errorf("poll: decode body: %w", err)
		}
		return resp.Invocation, nil
	default:
		return nil, decodeError(httpResp)
	}
}

// PostResult delivers the runner's result for a previously-leased
// invocation. After this call the invocation is terminal on the PostHog
// side; the runner discards local state for it.
func (c *Client) PostResult(ctx context.Context, invocationID string, req protocol.ResultRequest) error {
	return c.doJSON(ctx, http.MethodPost, "/runners/invocations/"+invocationID+"/result", req, nil)
}

// ExtendLease pushes out a leased invocation's expiry. Used by long-running
// tools (e.g. waiting on a k8s rollout) so PostHog doesn't re-queue the
// invocation thinking the runner died.
func (c *Client) ExtendLease(ctx context.Context, invocationID string, req protocol.ExtendLeaseRequest) (*protocol.ExtendLeaseResponse, error) {
	var resp protocol.ExtendLeaseResponse
	if err := c.doJSON(ctx, http.MethodPost, "/runners/invocations/"+invocationID+"/extend_lease", req, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

// doJSON encodes body to JSON, sends the request, and decodes a 2xx
// response body into out (skipped if out is nil).
func (c *Client) doJSON(ctx context.Context, method, path string, body, out any) error {
	var reqBody io.Reader
	if body != nil {
		buf, err := json.Marshal(body)
		if err != nil {
			return fmt.Errorf("encode body: %w", err)
		}
		reqBody = bytes.NewReader(buf)
	}
	httpReq, err := c.newRequest(ctx, method, path, reqBody)
	if err != nil {
		return err
	}
	if reqBody != nil {
		httpReq.Header.Set("Content-Type", "application/json")
	}
	httpResp, err := c.http.Do(httpReq)
	if err != nil {
		return fmt.Errorf("%s %s: %w", method, path, err)
	}
	defer httpResp.Body.Close()

	if httpResp.StatusCode < 200 || httpResp.StatusCode >= 300 {
		return decodeError(httpResp)
	}
	if out != nil && httpResp.ContentLength != 0 {
		if err := json.NewDecoder(httpResp.Body).Decode(out); err != nil {
			return fmt.Errorf("%s %s: decode body: %w", method, path, err)
		}
	}
	return nil
}

func (c *Client) newRequest(ctx context.Context, method, path string, body io.Reader) (*http.Request, error) {
	req, err := http.NewRequestWithContext(ctx, method, c.endpoint+path, body)
	if err != nil {
		return nil, fmt.Errorf("build request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+c.token)
	req.Header.Set("Accept", "application/json")
	return req, nil
}

// APIError is returned for non-2xx ingress responses. Carries the parsed
// error envelope where one is present, the raw body otherwise.
type APIError struct {
	StatusCode int
	Code       string
	Message    string
	Body       string
}

func (e *APIError) Error() string {
	if e.Code != "" {
		return fmt.Sprintf("ingress %d %s: %s", e.StatusCode, e.Code, e.Message)
	}
	return fmt.Sprintf("ingress %d: %s", e.StatusCode, e.Body)
}

func decodeError(resp *http.Response) error {
	body, _ := io.ReadAll(resp.Body)
	apiErr := &APIError{StatusCode: resp.StatusCode, Body: string(body)}
	var env protocol.ErrorResponse
	if err := json.Unmarshal(body, &env); err == nil {
		apiErr.Code = env.Code
		apiErr.Message = env.Message
	}
	return apiErr
}
