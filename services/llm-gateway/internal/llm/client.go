package llm

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"strings"
	"time"

	bifrost "github.com/maximhq/bifrost/core"
	"github.com/maximhq/bifrost/core/schemas"
	"github.com/posthog/posthog/services/llm-gateway/internal/config"
)

type Client struct {
	bifrost    *bifrost.Bifrost
	settings   *config.Settings
	httpClient *http.Client
}

type Account struct{ settings *config.Settings }

type Response struct {
	Body       any
	Usage      Usage
	RawChoices any
}

type Usage struct {
	InputTokens  int
	OutputTokens int
}

type StreamChunk struct {
	Data  []byte
	Usage Usage
}

type ProviderError struct {
	StatusCode int
	Message    string
	Type       string
	Code       any
}

func (e *ProviderError) Error() string { return e.Message }

func New(settings *config.Settings) (*Client, error) {
	bf, err := bifrost.Init(context.Background(), schemas.BifrostConfig{Account: &Account{settings: settings}, Logger: bifrost.NewNoOpLogger()})
	if err != nil {
		return nil, err
	}
	return &Client{bifrost: bf, settings: settings, httpClient: &http.Client{Timeout: settings.RequestTimeout}}, nil
}

func (c *Client) Close() { c.bifrost.Shutdown() }

func (a *Account) GetConfiguredProviders() ([]schemas.ModelProvider, error) {
	providers := []schemas.ModelProvider{}
	if a.settings.OpenAIAPIKey != "" {
		providers = append(providers, schemas.OpenAI)
	}
	if a.settings.AnthropicAPIKey != "" {
		providers = append(providers, schemas.Anthropic)
	}
	if a.settings.OpenRouterAPIKey != "" {
		providers = append(providers, schemas.OpenRouter)
	}
	if a.settings.FireworksAPIKey != "" {
		providers = append(providers, schemas.Fireworks)
	}
	if a.settings.BedrockRegionName != "" {
		providers = append(providers, schemas.Bedrock)
	}
	return providers, nil
}

func (a *Account) GetKeysForProvider(ctx context.Context, provider schemas.ModelProvider) ([]schemas.Key, error) {
	key := ""
	switch provider {
	case schemas.OpenAI:
		key = a.settings.OpenAIAPIKey
	case schemas.Anthropic:
		key = a.settings.AnthropicAPIKey
	case schemas.OpenRouter:
		key = a.settings.OpenRouterAPIKey
	case schemas.Fireworks:
		key = a.settings.FireworksAPIKey
	case schemas.Bedrock:
		return []schemas.Key{{ID: "bedrock", Name: "bedrock", Models: schemas.WhiteList{"*"}, Weight: 1, BedrockKeyConfig: &schemas.BedrockKeyConfig{Region: schemas.NewEnvVar(a.settings.BedrockRegionName)}}}, nil
	default:
		return nil, fmt.Errorf("provider %s not supported", provider)
	}
	if key == "" {
		return nil, fmt.Errorf("provider %s not configured", provider)
	}
	return []schemas.Key{{ID: string(provider), Name: string(provider), Value: *schemas.NewEnvVar(key), Models: schemas.WhiteList{"*"}, Weight: 1}}, nil
}

func (a *Account) GetConfigForProvider(provider schemas.ModelProvider) (*schemas.ProviderConfig, error) {
	network := schemas.DefaultNetworkConfig
	network.DefaultRequestTimeoutInSeconds = int(a.settings.RequestTimeout.Seconds())
	network.StreamIdleTimeoutInSeconds = int(a.settings.StreamingTimeout.Seconds())
	if provider == schemas.OpenAI && a.settings.OpenAIAPIBaseURL != "" {
		network.BaseURL = a.settings.OpenAIAPIBaseURL
	}
	return &schemas.ProviderConfig{NetworkConfig: network, ConcurrencyAndBufferSize: schemas.DefaultConcurrencyAndBufferSize, SendBackRawResponse: true}, nil
}

func ProviderFromModel(model string, fallback schemas.ModelProvider) (schemas.ModelProvider, string) {
	provider, parsed := schemas.ParseModelString(model, fallback)
	return provider, parsed
}

func NormalizeOpenAIModel(model string) string {
	if strings.HasPrefix(model, "openai/") {
		return strings.TrimPrefix(model, "openai/")
	}
	return model
}

func (c *Client) ChatCompletion(ctx context.Context, raw []byte, model string, provider schemas.ModelProvider, streaming bool, headers http.Header) (*Response, error) {
	sanitized, err := SanitizeJSON(raw, nil)
	if err != nil {
		return nil, err
	}
	providerModel := model
	if provider == schemas.OpenAI {
		providerModel = NormalizeOpenAIModel(model)
	}
	bctx := bifrostContext(ctx, c.settings.RequestTimeout, headers)
	req := &schemas.BifrostChatRequest{Provider: provider, Model: providerModel, RawRequestBody: sanitized}
	if streaming {
		return nil, errors.New("streaming requires ChatCompletionStream")
	}
	resp, bfErr := c.bifrost.ChatCompletionRequest(bctx, req)
	if bfErr != nil {
		return nil, convertBifrostError(bfErr)
	}
	body := responseBody(resp.ExtraFields.RawResponse, resp)
	usage := Usage{}
	if resp.Usage != nil {
		usage.InputTokens = resp.Usage.PromptTokens
		usage.OutputTokens = resp.Usage.CompletionTokens
	}
	return &Response{Body: body, Usage: usage, RawChoices: extract(body, "choices")}, nil
}

func (c *Client) ChatCompletionStream(ctx context.Context, raw []byte, model string, provider schemas.ModelProvider, headers http.Header) (<-chan StreamChunk, <-chan error, error) {
	sanitized, err := SanitizeJSON(raw, nil)
	if err != nil {
		return nil, nil, err
	}
	providerModel := model
	if provider == schemas.OpenAI {
		providerModel = NormalizeOpenAIModel(model)
	}
	bctx := bifrostContext(ctx, c.settings.StreamingTimeout, headers)
	stream, bfErr := c.bifrost.ChatCompletionStreamRequest(bctx, &schemas.BifrostChatRequest{Provider: provider, Model: providerModel, RawRequestBody: sanitized})
	if bfErr != nil {
		return nil, nil, convertBifrostError(bfErr)
	}
	out := make(chan StreamChunk)
	errs := make(chan error, 1)
	go func() {
		defer close(out)
		defer close(errs)
		for chunk := range stream {
			if chunk.BifrostError != nil {
				errs <- convertBifrostError(chunk.BifrostError)
				return
			}
			usage := Usage{}
			if chunk.BifrostChatResponse != nil && chunk.BifrostChatResponse.Usage != nil {
				usage.InputTokens = chunk.BifrostChatResponse.Usage.PromptTokens
				usage.OutputTokens = chunk.BifrostChatResponse.Usage.CompletionTokens
			}
			data, err := json.Marshal(chunk)
			if err != nil {
				errs <- err
				return
			}
			out <- StreamChunk{Data: append([]byte("data: "), append(data, []byte("\n\n")...)...), Usage: usage}
		}
		out <- StreamChunk{Data: []byte("data: [DONE]\n\n")}
	}()
	return out, errs, nil
}

func (c *Client) Responses(ctx context.Context, raw []byte, model string, streaming bool, headers http.Header) (*Response, error) {
	sanitized, err := SanitizeJSON(raw, map[string]any{"model": EnsureOpenAIPrefix(model)})
	if err != nil {
		return nil, err
	}
	bctx := bifrostContext(ctx, c.settings.RequestTimeout, headers)
	req := &schemas.BifrostResponsesRequest{Provider: schemas.OpenAI, Model: NormalizeOpenAIModel(model), RawRequestBody: sanitized}
	if streaming {
		return nil, errors.New("streaming requires ResponsesStream")
	}
	resp, bfErr := c.bifrost.ResponsesRequest(bctx, req)
	if bfErr != nil {
		return nil, convertBifrostError(bfErr)
	}
	body := responseBody(resp.ExtraFields.RawResponse, resp)
	usage := Usage{}
	if resp.Usage != nil {
		usage.InputTokens = resp.Usage.InputTokens
		usage.OutputTokens = resp.Usage.OutputTokens
	}
	return &Response{Body: body, Usage: usage, RawChoices: extract(body, "output")}, nil
}

func (c *Client) ResponsesStream(ctx context.Context, raw []byte, model string, headers http.Header) (<-chan StreamChunk, <-chan error, error) {
	sanitized, err := SanitizeJSON(raw, map[string]any{"model": EnsureOpenAIPrefix(model)})
	if err != nil {
		return nil, nil, err
	}
	bctx := bifrostContext(ctx, c.settings.StreamingTimeout, headers)
	stream, bfErr := c.bifrost.ResponsesStreamRequest(bctx, &schemas.BifrostResponsesRequest{Provider: schemas.OpenAI, Model: NormalizeOpenAIModel(model), RawRequestBody: sanitized})
	if bfErr != nil {
		return nil, nil, convertBifrostError(bfErr)
	}
	out := make(chan StreamChunk)
	errs := make(chan error, 1)
	go func() {
		defer close(out)
		defer close(errs)
		for chunk := range stream {
			if chunk.BifrostError != nil {
				errs <- convertBifrostError(chunk.BifrostError)
				return
			}
			data, err := json.Marshal(chunk)
			if err != nil {
				errs <- err
				return
			}
			out <- StreamChunk{Data: append([]byte("data: "), append(data, []byte("\n\n")...)...)}
		}
		out <- StreamChunk{Data: []byte("data: [DONE]\n\n")}
	}()
	return out, errs, nil
}

func (c *Client) AnthropicMessagesDirect(ctx context.Context, raw []byte, streaming bool, headers http.Header) (*http.Response, error) {
	sanitized, err := SanitizeJSON(raw, map[string]any{"stream": streaming})
	if err != nil {
		return nil, err
	}
	if c.settings.AnthropicAPIKey == "" {
		return nil, &ProviderError{StatusCode: 503, Message: "Anthropic API key not configured", Type: "configuration_error"}
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, "https://api.anthropic.com/v1/messages", bytes.NewReader(sanitized))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("x-api-key", c.settings.AnthropicAPIKey)
	req.Header.Set("anthropic-version", firstHeader(headers, "anthropic-version", "2023-06-01"))
	if beta := headers.Get("anthropic-beta"); beta != "" {
		req.Header.Set("anthropic-beta", beta)
	}
	return c.httpClient.Do(req)
}

func (c *Client) CountTokens(ctx context.Context, raw []byte) (*Response, error) {
	sanitized, err := SanitizeJSON(raw, nil)
	if err != nil {
		return nil, err
	}
	if c.settings.AnthropicAPIKey == "" {
		return nil, &ProviderError{StatusCode: 503, Message: "Anthropic API key not configured", Type: "configuration_error"}
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, "https://api.anthropic.com/v1/messages/count_tokens", bytes.NewReader(sanitized))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("x-api-key", c.settings.AnthropicAPIKey)
	req.Header.Set("anthropic-version", "2023-06-01")
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var body any
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, providerErrorFromBody(resp.StatusCode, body)
	}
	usage := Usage{InputTokens: intNumber(extract(body, "input_tokens"))}
	return &Response{Body: body, Usage: usage}, nil
}

func (c *Client) Transcription(ctx context.Context, fileName string, contentType string, content []byte, model string, language string) (*Response, error) {
	if c.settings.OpenAIAPIKey == "" {
		return nil, &ProviderError{StatusCode: 503, Message: "OpenAI API key not configured", Type: "configuration_error"}
	}
	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	part, err := writer.CreateFormFile("file", fileName)
	if err != nil {
		return nil, err
	}
	if _, err := part.Write(content); err != nil {
		return nil, err
	}
	_ = writer.WriteField("model", NormalizeOpenAIModel(model))
	if language != "" {
		_ = writer.WriteField("language", language)
	}
	if err := writer.Close(); err != nil {
		return nil, err
	}
	baseURL := strings.TrimRight(c.settings.OpenAIAPIBaseURL, "/")
	if baseURL == "" {
		baseURL = "https://api.openai.com"
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, baseURL+"/v1/audio/transcriptions", &body)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+c.settings.OpenAIAPIKey)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var parsed any
	if err := json.NewDecoder(resp.Body).Decode(&parsed); err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, providerErrorFromBody(resp.StatusCode, parsed)
	}
	return &Response{Body: parsed}, nil
}

func EnsureOpenAIPrefix(model string) string {
	if strings.HasPrefix(model, "openai/") {
		return model
	}
	return "openai/" + model
}

func SanitizeJSON(raw []byte, overlay map[string]any) ([]byte, error) {
	var value any
	if err := json.Unmarshal(raw, &value); err != nil {
		return nil, err
	}
	sanitized := sanitize(value)
	root, ok := sanitized.(map[string]any)
	if !ok {
		return nil, &ProviderError{StatusCode: 400, Message: "Request body must be a JSON object", Type: "invalid_request_error"}
	}
	for k, v := range overlay {
		root[k] = v
	}
	return json.Marshal(root)
}

func sanitize(value any) any {
	forbidden := map[string]bool{"api_key": true, "api_base": true, "base_url": true, "api_version": true, "organization": true, "model_list": true, "fallbacks": true, "custom_llm_provider": true}
	switch typed := value.(type) {
	case map[string]any:
		out := map[string]any{}
		for k, v := range typed {
			if forbidden[k] {
				continue
			}
			out[k] = sanitize(v)
		}
		return out
	case []any:
		out := make([]any, 0, len(typed))
		for _, item := range typed {
			out = append(out, sanitize(item))
		}
		return out
	default:
		return typed
	}
}

func bifrostContext(ctx context.Context, timeout time.Duration, headers http.Header) *schemas.BifrostContext {
	bctx := schemas.NewBifrostContext(ctx, time.Now().Add(timeout))
	bctx.SetValue(schemas.BifrostContextKeyUseRawRequestBody, true)
	bctx.SetValue(schemas.BifrostContextKeySendBackRawResponse, true)
	extra := map[string][]string{}
	if beta := headers.Values("anthropic-beta"); len(beta) > 0 {
		extra["anthropic-beta"] = beta
	}
	if len(extra) > 0 {
		bctx.SetValue(schemas.BifrostContextKeyExtraHeaders, extra)
	}
	return bctx
}

func convertBifrostError(err *schemas.BifrostError) error {
	status := 500
	if err.StatusCode != nil {
		status = *err.StatusCode
	}
	message := err.GetErrorString()
	errType := "internal_error"
	var code any
	if err.Error != nil {
		if err.Error.Message != "" {
			message = err.Error.Message
		}
		if err.Error.Type != nil {
			errType = *err.Error.Type
		}
		if err.Error.Code != nil {
			code = *err.Error.Code
		}
	}
	return &ProviderError{StatusCode: status, Message: message, Type: errType, Code: code}
}

func providerErrorFromBody(status int, body any) error {
	message := "Provider request failed"
	errType := "api_error"
	var code any
	if errObj, ok := extract(body, "error").(map[string]any); ok {
		if val, ok := errObj["message"].(string); ok {
			message = val
		}
		if val, ok := errObj["type"].(string); ok {
			errType = val
		}
		code = errObj["code"]
	}
	return &ProviderError{StatusCode: status, Message: message, Type: errType, Code: code}
}

func responseBody(raw any, fallback any) any {
	if raw == nil {
		return fallback
	}
	return raw
}

func extract(value any, key string) any {
	if object, ok := value.(map[string]any); ok {
		return object[key]
	}
	return nil
}

func intNumber(value any) int {
	switch typed := value.(type) {
	case float64:
		return int(typed)
	case int:
		return typed
	default:
		return 0
	}
}

func firstHeader(headers http.Header, key string, fallback string) string {
	if value := headers.Get(key); value != "" {
		return value
	}
	return fallback
}

func DecodeBody(resp *http.Response) (any, []byte, error) {
	bodyBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, nil, err
	}
	var parsed any
	if len(bodyBytes) > 0 {
		_ = json.Unmarshal(bodyBytes, &parsed)
	}
	return parsed, bodyBytes, nil
}
