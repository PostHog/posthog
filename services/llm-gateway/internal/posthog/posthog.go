package posthog

import (
	"bytes"
	"context"
	"encoding/json"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/posthog/posthog/services/llm-gateway/internal/auth"
	"github.com/posthog/posthog/services/llm-gateway/internal/config"
)

type Client struct {
	settings   *config.Settings
	httpClient *http.Client
}

type Event struct {
	DistinctID string         `json:"distinct_id"`
	Event      string         `json:"event"`
	Properties map[string]any `json:"properties"`
	Groups     map[string]any `json:"groups,omitempty"`
	Timestamp  string         `json:"timestamp,omitempty"`
	APIKey     string         `json:"api_key"`
}

func New(settings *config.Settings) *Client {
	return &Client{settings: settings, httpClient: &http.Client{Timeout: 5 * time.Second}}
}

func (c *Client) CaptureAIGeneration(ctx context.Context, user *auth.User, product string, provider string, model string, input any, response any, usage Usage, latency float64, streaming bool, endUserID string, properties map[string]any, flags map[string]any, traceID string, isError bool, errorMessage string) {
	if c.settings.PostHogProjectToken == "" {
		return
	}
	distinctID := endUserID
	if user != nil && user.AuthMethod == "oauth_access_token" {
		distinctID = user.DistinctID
	}
	if distinctID == "" && user != nil {
		distinctID = user.DistinctID
	}
	if distinctID == "" {
		distinctID = uuid.NewString()
	}
	if traceID == "" {
		traceID = uuid.NewString()
	} else if _, err := uuid.Parse(traceID); err != nil {
		traceID = uuid.NewSHA1(uuid.MustParse("8d4f6b7e-6a3e-4f3a-9f3b-3b6f4d2e8a1a"), []byte(traceID)).String()
	}
	props := map[string]any{
		"$ai_model":         model,
		"$ai_provider":      provider,
		"$ai_input":         sanitizeBinary(input),
		"$ai_input_tokens":  usage.InputTokens,
		"$ai_output_tokens": usage.OutputTokens,
		"$ai_latency":       latency,
		"$ai_stream":        streaming,
		"$ai_trace_id":      traceID,
		"$ai_span_id":       uuid.NewString(),
		"ai_product":        product,
	}
	if isError {
		props["$ai_is_error"] = true
		props["$ai_error"] = errorMessage
	} else if response != nil {
		props["$ai_output_choices"] = sanitizeBinary(response)
	}
	if usage.TotalCostUSD > 0 {
		props["$ai_total_cost_usd"] = usage.TotalCostUSD
	}
	if usage.TimeToFirstToken > 0 {
		props["$ai_time_to_first_token"] = usage.TimeToFirstToken
	}
	if user != nil && user.TeamID != nil {
		props["team_id"] = *user.TeamID
	}
	for k, v := range properties {
		props[k] = v
	}
	for k, v := range flags {
		props["$feature/"+k] = v
	}
	props = truncateForCapture(props)
	payload := Event{DistinctID: distinctID, Event: "$ai_generation", Properties: props, APIKey: c.settings.PostHogProjectToken, Timestamp: time.Now().UTC().Format(time.RFC3339Nano)}
	if user != nil && user.TeamID != nil {
		payload.Groups = map[string]any{"project": *user.TeamID}
	}
	go c.capture(payload)
}

func (c *Client) capture(payload Event) {
	body, err := json.Marshal(payload)
	if err != nil {
		return
	}
	endpoint := strings.TrimRight(c.settings.PostHogHost, "/") + "/capture/"
	req, err := http.NewRequest(http.MethodPost, endpoint, bytes.NewReader(body))
	if err != nil {
		return
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.httpClient.Do(req)
	if err != nil {
		log.Printf("posthog_capture_failed: %v", err)
		return
	}
	_ = resp.Body.Close()
}

type Usage struct {
	InputTokens      int
	OutputTokens     int
	TotalCostUSD     float64
	TimeToFirstToken float64
}

func sanitizeBinary(value any) any {
	switch v := value.(type) {
	case []byte:
		return map[string]any{"type": "binary", "size_bytes": len(v)}
	case map[string]any:
		out := map[string]any{}
		for k, item := range v {
			out[k] = sanitizeBinary(item)
		}
		return out
	case []any:
		out := make([]any, 0, len(v))
		for _, item := range v {
			out = append(out, sanitizeBinary(item))
		}
		return out
	default:
		return value
	}
}

const maxCaptureSize = 15 * 1024 * 1024
const minFieldSizeToTruncate = 10 * 1024
const truncationMarker = "[truncated: content too large for capture]"

func truncateForCapture(properties map[string]any) map[string]any {
	if jsonSize(properties) <= maxCaptureSize {
		return properties
	}
	result := map[string]any{}
	for k, v := range properties {
		result[k] = v
	}
	for _, field := range []string{"$ai_output_choices", "$ai_input"} {
		if jsonSize(result[field]) < minFieldSizeToTruncate {
			continue
		}
		result[field] = truncationMarker
		if jsonSize(result) <= maxCaptureSize {
			break
		}
	}
	return result
}

func jsonSize(value any) int {
	payload, err := json.Marshal(value)
	if err != nil {
		return 0
	}
	return len(payload)
}
