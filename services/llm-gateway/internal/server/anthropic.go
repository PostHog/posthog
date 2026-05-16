package server

import (
	"bufio"
	"context"
	"encoding/json"
	"github.com/maximhq/bifrost/core/schemas"
	"github.com/posthog/posthog/services/llm-gateway/internal/llm"
	"github.com/posthog/posthog/services/llm-gateway/internal/metrics"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"
)

func (a *App) anthropicMessages(w http.ResponseWriter, r *http.Request) {
	raw, req, ok := a.prepareJSONRequest(w, r, "anthropic_messages", []string{"model", "messages"})
	if !ok {
		return
	}
	provider, valid := providerFromHeaders(r)
	if !valid {
		writeError(w, 400, "Expected one of: anthropic, bedrock", "invalid_request_error", nil)
		return
	}
	req.provider = provider
	start := time.Now()
	if req.stream {
		if provider == "bedrock" {
			stream, errs, err := a.llm.AnthropicMessagesStream(r.Context(), raw, req.model, schemas.Bedrock, r.Header)
			if err != nil {
				a.writeProviderError(w, err, req, "anthropic_messages", start, true)
				return
			}
			a.writeStream(w, stream, errs, req, "anthropic_messages", start)
			return
		}
		resp, err := a.llm.AnthropicMessagesDirect(r.Context(), raw, true, r.Header)
		if err != nil {
			a.writeProviderError(w, err, req, "anthropic_messages", start, true)
			return
		}
		defer resp.Body.Close()
		if resp.StatusCode >= 400 {
			writeUpstreamResponse(w, resp)
			metrics.RequestCount.WithLabelValues("anthropic_messages", provider, req.model, strconv.Itoa(resp.StatusCode), req.user.AuthMethod, req.product).Inc()
			metrics.RequestLatency.WithLabelValues("anthropic_messages", provider, "true", req.product).Observe(time.Since(start).Seconds())
			return
		}
		usage, output, ttft, err := a.proxyAnthropicStream(w, resp, start)
		if err != nil {
			a.writeStreamError(req, "anthropic_messages", start, err)
			return
		}
		req.timeToFirstToken = ttft
		a.afterSuccess(context.Background(), req, "anthropic_messages", start, true, &llm.Response{Usage: usage, RawChoices: output})
		return
	}
	bfProvider := schemas.Anthropic
	if provider == "bedrock" {
		bfProvider = schemas.Bedrock
	}
	response, err := a.llm.AnthropicMessages(r.Context(), raw, req.model, bfProvider, r.Header)
	if err != nil && provider == "anthropic" && useBedrockFallback(r) && statusCode(err) >= 500 {
		metrics.BedrockFallbackTriggered.WithLabelValues(req.model, req.product, errorType(err)).Inc()
		req.provider = "bedrock"
		response, err = a.llm.AnthropicMessages(r.Context(), raw, req.model, schemas.Bedrock, r.Header)
		if err == nil {
			metrics.BedrockFallbackSuccess.WithLabelValues(req.model, req.product).Inc()
		}
	}
	if err != nil {
		if req.provider == "bedrock" {
			metrics.BedrockFallbackFailure.WithLabelValues(req.model, req.product).Inc()
		}
		a.writeProviderError(w, err, req, "anthropic_messages", start, false)
		return
	}
	a.afterSuccess(r.Context(), req, "anthropic_messages", start, false, response)
	writeJSON(w, 200, response.Body)
}

func (a *App) countTokens(w http.ResponseWriter, r *http.Request) {
	raw, req, ok := a.prepareJSONRequest(w, r, "anthropic_count_tokens", []string{"model", "messages"})
	if !ok {
		return
	}
	provider, valid := providerFromHeaders(r)
	if !valid {
		writeError(w, 400, "Expected one of: anthropic, bedrock", "invalid_request_error", nil)
		return
	}
	start := time.Now()
	var resp *llm.Response
	var err error
	if provider == "bedrock" {
		req.provider = "bedrock"
		resp, err = a.llm.CountTokensBifrost(r.Context(), raw, req.model, schemas.Bedrock)
	} else {
		resp, err = a.llm.CountTokens(r.Context(), raw)
	}
	if err != nil {
		a.writeProviderError(w, err, req, "anthropic_count_tokens", start, false)
		return
	}
	metrics.RequestCount.WithLabelValues("anthropic_count_tokens", req.provider, req.model, "200", req.user.AuthMethod, req.product).Inc()
	metrics.RequestLatency.WithLabelValues("anthropic_count_tokens", req.provider, "false", req.product).Observe(time.Since(start).Seconds())
	writeJSON(w, 200, resp.Body)
}

func (a *App) proxyAnthropicStream(w http.ResponseWriter, resp *http.Response, start time.Time) (llm.Usage, any, float64, error) {
	for k, values := range resp.Header {
		if strings.EqualFold(k, "content-length") {
			continue
		}
		for _, value := range values {
			w.Header().Add(k, value)
		}
	}
	w.WriteHeader(resp.StatusCode)
	flusher, _ := w.(http.Flusher)
	usage := llm.Usage{}
	output := []any{}
	ttft := 0.0
	scanner := bufio.NewScanner(resp.Body)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	for scanner.Scan() {
		line := scanner.Bytes()
		if len(line) > 6 && string(line[:6]) == "data: " {
			if ttft == 0 {
				ttft = time.Since(start).Seconds()
			}
			updateAnthropicStreamUsage(line[6:], &usage)
			if parsed := parseAnthropicStreamOutput(line[6:]); parsed != nil {
				output = append(output, parsed)
			}
		}
		if _, err := w.Write(append(append([]byte{}, line...), '\n')); err != nil {
			metrics.StreamingClientDisconnect.WithLabelValues("anthropic", "unknown", "unknown").Inc()
			return usage, output, ttft, err
		}
		if flusher != nil {
			flusher.Flush()
		}
	}
	return usage, output, ttft, scanner.Err()
}

func parseAnthropicStreamOutput(data []byte) any {
	var event map[string]any
	if err := json.Unmarshal(data, &event); err != nil {
		return nil
	}
	if event["type"] == "content_block_delta" || event["type"] == "message_delta" {
		return event
	}
	return nil
}

func updateAnthropicStreamUsage(data []byte, usage *llm.Usage) {
	var event map[string]any
	if err := json.Unmarshal(data, &event); err != nil {
		return
	}
	usageObject, _ := event["usage"].(map[string]any)
	if input := intNumber(usageObject["input_tokens"]); input > 0 {
		usage.InputTokens = input
	}
	if output := intNumber(usageObject["output_tokens"]); output > 0 {
		usage.OutputTokens = output
	}
}

func writeUpstreamResponse(w http.ResponseWriter, resp *http.Response) {
	for k, values := range resp.Header {
		if strings.EqualFold(k, "content-length") {
			continue
		}
		for _, value := range values {
			w.Header().Add(k, value)
		}
	}
	w.WriteHeader(resp.StatusCode)
	_, _ = io.Copy(w, resp.Body)
}

func useBedrockFallback(r *http.Request) bool {
	value := strings.ToLower(r.Header.Get("X-PostHog-Use-Bedrock-Fallback"))
	return value == "true"
}
