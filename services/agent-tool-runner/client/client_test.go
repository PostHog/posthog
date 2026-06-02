package client

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/posthog/posthog/services/agent-tool-runner/protocol"
)

func TestNew_RequiresEndpointAndToken(t *testing.T) {
	cases := []struct {
		name string
		opts Options
		want string
	}{
		{"no endpoint", Options{Token: "t"}, "endpoint is required"},
		{"no token", Options{Endpoint: "https://x"}, "token is required"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := New(tc.opts)
			if err == nil || !strings.Contains(err.Error(), tc.want) {
				t.Errorf("expected error containing %q, got %v", tc.want, err)
			}
		})
	}
}

func TestHeartbeat_PostsBodyAndAuth(t *testing.T) {
	srv := newTestIngress(t)
	defer srv.Close()

	c := mustNewClient(t, srv.URL, "tok-abc")
	_, err := c.Heartbeat(context.Background(), protocol.HeartbeatRequest{
		InstanceID: "inst-1",
		Version:    "dev",
		Tools:      []protocol.ToolDescriptor{{Name: "x", InputSchema: json.RawMessage(`{}`)}},
	})
	if err != nil {
		t.Fatalf("Heartbeat: %v", err)
	}

	srv.assertLastRequest(t, http.MethodPost, "/runners/heartbeat")
	if got := srv.lastReq.Header.Get("Authorization"); got != "Bearer tok-abc" {
		t.Errorf("auth header = %q; want Bearer tok-abc", got)
	}
	var hb protocol.HeartbeatRequest
	if err := json.Unmarshal(srv.lastBody, &hb); err != nil {
		t.Fatalf("decode body: %v", err)
	}
	if hb.InstanceID != "inst-1" || len(hb.Tools) != 1 {
		t.Errorf("unexpected body: %+v", hb)
	}
}

func TestPoll_NoWork(t *testing.T) {
	srv := newTestIngress(t)
	srv.handler = func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNoContent)
	}
	defer srv.Close()

	c := mustNewClient(t, srv.URL, "tok")
	inv, err := c.Poll(context.Background(), 1*time.Second)
	if err != nil {
		t.Fatalf("Poll: %v", err)
	}
	if inv != nil {
		t.Errorf("expected nil invocation on 204, got %+v", inv)
	}
}

func TestPoll_LeasedInvocation(t *testing.T) {
	srv := newTestIngress(t)
	srv.handler = func(w http.ResponseWriter, r *http.Request) {
		body := protocol.PollResponse{Invocation: &protocol.LeasedInvocation{
			ID:                "inv-1",
			ToolName:          "grafana.query_loki",
			Args:              json.RawMessage(`{"q":"foo"}`),
			LeaseExpiresAtISO: "2030-01-01T00:00:00Z",
			SessionID:         "sess-1",
		}}
		json.NewEncoder(w).Encode(body)
	}
	defer srv.Close()

	c := mustNewClient(t, srv.URL, "tok")
	inv, err := c.Poll(context.Background(), 1*time.Second)
	if err != nil {
		t.Fatalf("Poll: %v", err)
	}
	if inv == nil || inv.ID != "inv-1" {
		t.Errorf("expected inv-1, got %+v", inv)
	}
	// Verify max_wait_seconds was forwarded as a query param.
	got := srv.lastReq.URL.Query().Get("max_wait_seconds")
	if got != "1" {
		t.Errorf("max_wait_seconds=%q; want 1", got)
	}
}

func TestPostResult_DoneAndFailed(t *testing.T) {
	cases := []struct {
		name string
		req  protocol.ResultRequest
	}{
		{"done", protocol.ResultRequest{Status: "done", Result: json.RawMessage(`"ok"`)}},
		{"failed", protocol.ResultRequest{Status: "failed", Error: "boom"}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			srv := newTestIngress(t)
			defer srv.Close()

			c := mustNewClient(t, srv.URL, "tok")
			if err := c.PostResult(context.Background(), "inv-99", tc.req); err != nil {
				t.Fatalf("PostResult: %v", err)
			}
			srv.assertLastRequest(t, http.MethodPost, "/runners/invocations/inv-99/result")
		})
	}
}

func TestExtendLease(t *testing.T) {
	srv := newTestIngress(t)
	srv.handler = func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(protocol.ExtendLeaseResponse{
			LeaseExpiresAtISO: "2030-01-01T00:01:00Z",
		})
	}
	defer srv.Close()

	c := mustNewClient(t, srv.URL, "tok")
	resp, err := c.ExtendLease(context.Background(), "inv-7", protocol.ExtendLeaseRequest{ExtendBySeconds: 60})
	if err != nil {
		t.Fatalf("ExtendLease: %v", err)
	}
	if resp.LeaseExpiresAtISO != "2030-01-01T00:01:00Z" {
		t.Errorf("unexpected response: %+v", resp)
	}
	srv.assertLastRequest(t, http.MethodPost, "/runners/invocations/inv-7/extend_lease")
}

func TestAPIError_StructuredEnvelope(t *testing.T) {
	srv := newTestIngress(t)
	srv.handler = func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusForbidden)
		json.NewEncoder(w).Encode(protocol.ErrorResponse{
			Code:    "runner_revoked",
			Message: "token was revoked",
		})
	}
	defer srv.Close()

	c := mustNewClient(t, srv.URL, "tok")
	_, err := c.Heartbeat(context.Background(), protocol.HeartbeatRequest{})
	var apiErr *APIError
	if !errors.As(err, &apiErr) {
		t.Fatalf("expected APIError, got %T: %v", err, err)
	}
	if apiErr.StatusCode != http.StatusForbidden || apiErr.Code != "runner_revoked" {
		t.Errorf("unexpected APIError: %+v", apiErr)
	}
	if !strings.Contains(apiErr.Error(), "runner_revoked") {
		t.Errorf("APIError.Error() should mention the code; got %q", apiErr.Error())
	}
}

func TestAPIError_NonJSONBody(t *testing.T) {
	srv := newTestIngress(t)
	srv.handler = func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadGateway)
		w.Write([]byte("upstream blew up"))
	}
	defer srv.Close()

	c := mustNewClient(t, srv.URL, "tok")
	_, err := c.Heartbeat(context.Background(), protocol.HeartbeatRequest{})
	var apiErr *APIError
	if !errors.As(err, &apiErr) {
		t.Fatalf("expected APIError, got %T", err)
	}
	if apiErr.StatusCode != http.StatusBadGateway || !strings.Contains(apiErr.Body, "upstream blew up") {
		t.Errorf("unexpected APIError: %+v", apiErr)
	}
}

func TestContextCancellation(t *testing.T) {
	srv := newTestIngress(t)
	srv.handler = func(w http.ResponseWriter, r *http.Request) {
		<-r.Context().Done()
	}
	defer srv.Close()

	c := mustNewClient(t, srv.URL, "tok")
	ctx, cancel := context.WithCancel(context.Background())
	cancel() // cancel before sending
	_, err := c.Poll(ctx, 30*time.Second)
	if err == nil {
		t.Fatal("expected error from cancelled context")
	}
}

// testIngress is a tiny httptest.Server wrapper that records the last
// request it saw, so individual tests can introspect headers + body
// without per-test plumbing.
type testIngress struct {
	*httptest.Server
	handler  http.HandlerFunc
	lastReq  *http.Request
	lastBody []byte
}

func newTestIngress(t *testing.T) *testIngress {
	t.Helper()
	ing := &testIngress{}
	ing.Server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ing.lastReq = r
		body, _ := readAll(r)
		ing.lastBody = body
		if ing.handler != nil {
			ing.handler(w, r)
			return
		}
		w.WriteHeader(http.StatusOK)
	}))
	return ing
}

func (ing *testIngress) assertLastRequest(t *testing.T, method, path string) {
	t.Helper()
	if ing.lastReq == nil {
		t.Fatal("no request recorded")
	}
	if ing.lastReq.Method != method {
		t.Errorf("method = %q; want %q", ing.lastReq.Method, method)
	}
	if ing.lastReq.URL.Path != path {
		t.Errorf("path = %q; want %q", ing.lastReq.URL.Path, path)
	}
}

func mustNewClient(t *testing.T, endpoint, token string) *Client {
	t.Helper()
	c, err := New(Options{Endpoint: endpoint, Token: token})
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	return c
}

func readAll(r *http.Request) ([]byte, error) {
	if r.Body == nil {
		return nil, nil
	}
	defer r.Body.Close()
	var buf [4096]byte
	n, err := r.Body.Read(buf[:])
	if err != nil && err.Error() != "EOF" {
		return nil, err
	}
	return buf[:n], nil
}
