package server

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/maximhq/bifrost/core/schemas"
	"github.com/posthog/posthog/services/llm-gateway/internal/auth"
	"github.com/posthog/posthog/services/llm-gateway/internal/config"
	"github.com/posthog/posthog/services/llm-gateway/internal/llm"
	"github.com/posthog/posthog/services/llm-gateway/internal/metrics"
	ph "github.com/posthog/posthog/services/llm-gateway/internal/posthog"
	"github.com/posthog/posthog/services/llm-gateway/internal/products"
	"github.com/posthog/posthog/services/llm-gateway/internal/ratelimit"
	"github.com/posthog/posthog/services/llm-gateway/internal/services"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/redis/go-redis/v9"
	"github.com/rs/cors"
)

type App struct {
	settings     *config.Settings
	db           *pgxpool.Pool
	redis        *redis.Client
	auth         *auth.Service
	limiter      *ratelimit.Runner
	llm          *llm.Client
	posthog      *ph.Client
	planResolver *services.PlanResolver
	mux          *http.ServeMux
}

type requestState struct {
	id               string
	product          string
	user             *auth.User
	model            string
	provider         string
	endUserID        string
	properties       map[string]any
	flags            map[string]any
	traceID          string
	stream           bool
	input            any
	planInfo         services.PlanInfo
	timeToFirstToken float64
	streamOutput     any
}

func New(settings *config.Settings) (*App, error) {
	ctx := context.Background()
	dbConfig, err := pgxpool.ParseConfig(settings.DatabaseURL)
	if err != nil {
		return nil, err
	}
	dbConfig.MinConns = int32(settings.DBPoolMinSize)
	dbConfig.MaxConns = int32(settings.DBPoolMaxSize)
	db, err := pgxpool.NewWithConfig(ctx, dbConfig)
	if err != nil {
		return nil, err
	}
	redisClient := redisFromSettings(ctx, settings)
	llmClient, err := llm.New(settings)
	if err != nil {
		db.Close()
		if redisClient != nil {
			_ = redisClient.Close()
		}
		return nil, err
	}
	app := &App{settings: settings, db: db, redis: redisClient, llm: llmClient, posthog: ph.New(settings), planResolver: services.NewPlanResolver(redisClient, settings)}
	app.auth = auth.New(db, settings)
	app.limiter = ratelimit.New(redisClient, settings)
	app.routes()
	return app, nil
}

func (a *App) Close() {
	if a.llm != nil {
		a.llm.Close()
	}
	if a.redis != nil {
		_ = a.redis.Close()
	}
	if a.db != nil {
		a.db.Close()
	}
}

func (a *App) Handler() http.Handler {
	handler := http.Handler(a.mux)
	handler = a.requestMiddleware(handler)
	return cors.New(cors.Options{AllowedOrigins: a.settings.CorsOrigins, AllowedMethods: []string{"GET", "POST", "OPTIONS"}, AllowedHeaders: []string{"*"}}).Handler(handler)
}

func (a *App) routes() {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /", a.root)
	mux.HandleFunc("GET /_liveness", a.liveness)
	mux.HandleFunc("GET /_readiness", a.readiness)
	mux.HandleFunc("GET /v1/models", a.models)
	mux.HandleFunc("GET /{product}/v1/models", a.models)
	mux.HandleFunc("GET /v1/usage/{product}", a.usage)
	mux.HandleFunc("POST /v1/usage/{product}/invalidate-plan-cache", a.invalidatePlanCache)
	mux.HandleFunc("POST /v1/chat/completions", a.chatCompletions)
	mux.HandleFunc("POST /{product}/v1/chat/completions", a.chatCompletions)
	mux.HandleFunc("POST /v1/responses", a.responses)
	mux.HandleFunc("POST /{product}/v1/responses", a.responses)
	mux.HandleFunc("POST /responses", a.responses)
	mux.HandleFunc("POST /{product}/responses", a.responses)
	mux.HandleFunc("POST /v1/messages", a.anthropicMessages)
	mux.HandleFunc("POST /{product}/v1/messages", a.anthropicMessages)
	mux.HandleFunc("POST /v1/messages/count_tokens", a.countTokens)
	mux.HandleFunc("POST /{product}/v1/messages/count_tokens", a.countTokens)
	mux.HandleFunc("POST /v1/audio/transcriptions", a.transcriptions)
	mux.HandleFunc("POST /{product}/v1/audio/transcriptions", a.transcriptions)
	if a.settings.MetricsEnabled {
		mux.Handle("GET /metrics", promhttp.HandlerFor(metrics.Registry, promhttp.HandlerOpts{}))
	}
	a.mux = mux
}

func (a *App) requestMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requestID := r.Header.Get("x-request-id")
		if requestID == "" {
			requestID = uuid.NewString()[:8]
		}
		start := time.Now()
		w.Header().Set("x-request-id", requestID)
		rw := &responseWriter{ResponseWriter: w, status: 200}
		next.ServeHTTP(rw, r.WithContext(context.WithValue(r.Context(), stateKey{}, &requestState{id: requestID})))
		if r.URL.Path != "/_liveness" && r.URL.Path != "/_readiness" && r.URL.Path != "/metrics" {
			log.Printf("request method=%s path=%s status=%d duration_ms=%.2f", r.Method, r.URL.Path, rw.status, float64(time.Since(start).Microseconds())/1000)
		}
		if a.db != nil {
			stat := a.db.Stat()
			metrics.DBPoolSize.WithLabelValues("idle").Set(float64(stat.IdleConns()))
			metrics.DBPoolSize.WithLabelValues("active").Set(float64(stat.AcquiredConns()))
		}
	})
}

type stateKey struct{}

type responseWriter struct {
	http.ResponseWriter
	status int
}

func (w *responseWriter) WriteHeader(status int) {
	w.status = status
	w.ResponseWriter.WriteHeader(status)
}

func (w *responseWriter) Flush() {
	if flusher, ok := w.ResponseWriter.(http.Flusher); ok {
		flusher.Flush()
	}
}

func (a *App) prepareJSONRequest(w http.ResponseWriter, r *http.Request, endpoint string, required []string) ([]byte, *requestState, bool) {
	req, ok := a.authenticateOnly(w, r)
	if !ok {
		return nil, nil, false
	}
	raw, err := readLimited(r.Body, a.settings.MaxRequestBodySize)
	if err != nil {
		writeError(w, 413, "Request body too large", "request_too_large", nil)
		return nil, nil, false
	}
	var body map[string]any
	if err := json.Unmarshal(raw, &body); err != nil {
		writeError(w, 400, "Invalid JSON body", "invalid_request_error", nil)
		return nil, nil, false
	}
	missing := []string{}
	for _, field := range required {
		if _, ok := body[field]; !ok {
			missing = append(missing, field)
		}
	}
	if len(missing) > 0 {
		writeJSON(w, 422, map[string]any{"detail": missing})
		return nil, nil, false
	}
	model, _ := body["model"].(string)
	if model == "" {
		writeJSON(w, 422, map[string]any{"detail": []string{"model"}})
		return nil, nil, false
	}
	if unsupportedModel(model) {
		writeError(w, 400, fmt.Sprintf("Model '%s' is not supported by this gateway", model), "invalid_request_error", "model_not_supported")
		return nil, nil, false
	}
	provider := ""
	if endpoint == "anthropic_messages" || endpoint == "anthropic_count_tokens" {
		var valid bool
		provider, valid = providerFromHeaders(r)
		if !valid {
			writeError(w, 400, "Expected one of: anthropic, bedrock", "invalid_request_error", nil)
			return nil, nil, false
		}
	} else {
		parsedProvider, _ := llm.ProviderFromModel(model, schemas.OpenAI)
		provider = string(parsedProvider)
	}
	if allowed, msg := products.CheckAccess(a.settings, req.product, req.user, model, provider); !allowed {
		writeError(w, 403, msg, "permission_error", nil)
		return nil, nil, false
	}
	sanitizedBody, _ := llm.SanitizeJSON(raw, nil)
	var captureInput any
	_ = json.Unmarshal(sanitizedBody, &captureInput)
	req.input = captureInput
	req.model = model
	req.provider = provider
	req.stream, _ = body["stream"].(bool)
	req.endUserID = endUserID(body, req.user)
	req.traceID = traceID(body)
	req.planInfo = a.planResolver.Resolve(r.Context(), req.user.UserID, req.product, r.Header.Get("Authorization"))
	result := a.limiter.Check(r.Context(), req.user, req.product, req.endUserID, req.planInfo)
	if !result.Allowed {
		metrics.RateLimitExceeded.WithLabelValues(result.Detail).Inc()
		writeJSONWithHeaders(w, result.StatusCode, map[string]any{"error": map[string]any{"message": "Rate limit exceeded", "type": "rate_limit_error", "reason": result.Detail}}, map[string]string{"Retry-After": strconv.Itoa(result.RetryAfter)})
		return nil, nil, false
	}
	_ = endpoint
	return raw, req, true
}

func (a *App) authenticateOnly(w http.ResponseWriter, r *http.Request) (*requestState, bool) {
	product := pathProduct(r)
	if err := products.Validate(product); err != nil {
		writeJSON(w, 400, map[string]string{"detail": err.Error()})
		return nil, false
	}
	user, err := a.auth.AuthenticateHeaders(r.Context(), r.Header)
	if err != nil {
		writeError(w, 401, "Authentication required", "authentication_error", nil)
		return nil, false
	}
	if user == nil {
		writeJSON(w, 401, map[string]string{"detail": "Authentication required"})
		return nil, false
	}
	state := getState(r)
	state.product = products.ResolveAlias(product)
	state.user = user
	state.properties = posthogProperties(r.Header)
	state.flags = posthogFlags(r.Header)
	return state, true
}

func (a *App) afterSuccess(ctx context.Context, req *requestState, endpoint string, start time.Time, streaming bool, resp *llm.Response) {
	latency := time.Since(start).Seconds()
	metrics.RequestCount.WithLabelValues(endpoint, req.provider, req.model, "200", req.user.AuthMethod, req.product).Inc()
	metrics.RequestLatency.WithLabelValues(endpoint, req.provider, strconv.FormatBool(streaming), req.product).Observe(latency)
	metrics.LLMRequests.WithLabelValues(req.provider, req.model, req.product, strconv.FormatBool(streaming)).Inc()
	metrics.CallbackSuccess.WithLabelValues("prometheus").Inc()
	metrics.CallbackSuccess.WithLabelValues("rate_limit").Inc()
	usage := ph.Usage{InputTokens: resp.Usage.InputTokens, OutputTokens: resp.Usage.OutputTokens, TimeToFirstToken: req.timeToFirstToken}
	if usage.InputTokens > 0 {
		metrics.TokensInput.WithLabelValues(req.provider, req.model, req.product).Add(float64(usage.InputTokens))
	}
	if usage.OutputTokens > 0 {
		metrics.TokensOutput.WithLabelValues(req.provider, req.model, req.product).Add(float64(usage.OutputTokens))
	}
	cost := estimateCost(req.model, req.provider, usage.InputTokens, usage.OutputTokens)
	if cost > 0 {
		metrics.CostEstimated.WithLabelValues(req.provider, req.model, req.product).Inc()
	} else {
		cost = a.settings.DefaultFallbackCostUSD
		metrics.CostFallbackDefault.WithLabelValues(req.provider, req.model, req.product).Inc()
		metrics.CostMissing.WithLabelValues(req.provider, req.model, req.product).Inc()
	}
	usage.TotalCostUSD = cost
	metrics.CostRecorded.WithLabelValues(req.provider, req.model, req.product).Add(cost)
	metrics.CostUSD.WithLabelValues(req.provider, req.model, req.product).Add(cost)
	a.limiter.RecordCost(ctx, req.user, req.product, req.endUserID, cost, req.planInfo)
	output := resp.RawChoices
	if output == nil {
		output = req.streamOutput
	}
	if output == nil {
		output = resp.Body
	}
	a.posthog.CaptureAIGeneration(ctx, req.user, req.product, req.provider, req.model, captureInput(req), output, usage, latency, streaming, req.endUserID, req.properties, req.flags, req.traceID, false, "")
}

func (a *App) writeProviderError(w http.ResponseWriter, err error, req *requestState, endpoint string, start time.Time, streaming bool) {
	status := 500
	message := err.Error()
	errType := "internal_error"
	var code any
	var providerErr *llm.ProviderError
	if errors.As(err, &providerErr) {
		status = providerErr.StatusCode
		message = providerErr.Message
		errType = providerErr.Type
		code = providerErr.Code
	}
	metrics.ProviderErrors.WithLabelValues(req.provider, errType, req.product).Inc()
	metrics.RequestCount.WithLabelValues(endpoint, req.provider, req.model, strconv.Itoa(status), req.user.AuthMethod, req.product).Inc()
	metrics.RequestLatency.WithLabelValues(endpoint, req.provider, strconv.FormatBool(streaming), req.product).Observe(time.Since(start).Seconds())
	a.posthog.CaptureAIGeneration(context.Background(), req.user, req.product, req.provider, req.model, captureInput(req), nil, ph.Usage{}, time.Since(start).Seconds(), streaming, req.endUserID, req.properties, req.flags, req.traceID, true, message)
	writeError(w, status, message, errType, code)
}

func (a *App) writeStream(w http.ResponseWriter, stream <-chan llm.StreamChunk, errs <-chan error, req *requestState, endpoint string, start time.Time) {
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("X-Accel-Buffering", "no")
	flusher, _ := w.(http.Flusher)
	metrics.ActiveStreams.WithLabelValues(req.provider, req.model, req.product).Inc()
	defer metrics.ActiveStreams.WithLabelValues(req.provider, req.model, req.product).Dec()
	usage := llm.Usage{}
	first := true
	streamOutput := []any{}
	for chunk := range stream {
		if first {
			req.timeToFirstToken = time.Since(start).Seconds()
			metrics.LLMTimeToFirstToken.WithLabelValues(req.provider, req.model, req.product).Observe(req.timeToFirstToken)
			first = false
		}
		if len(chunk.Data) > 0 {
			streamOutput = append(streamOutput, string(chunk.Data))
		}
		if chunk.Usage.InputTokens > 0 {
			usage.InputTokens = chunk.Usage.InputTokens
		}
		if chunk.Usage.OutputTokens > 0 {
			usage.OutputTokens = chunk.Usage.OutputTokens
		}
		_, _ = w.Write(chunk.Data)
		if flusher != nil {
			flusher.Flush()
		}
	}
	select {
	case err := <-errs:
		if err != nil {
			a.writeStreamError(req, endpoint, start, err)
			return
		}
	default:
	}
	req.streamOutput = streamOutput
	a.afterSuccess(context.Background(), req, endpoint, start, true, &llm.Response{Usage: usage})
}

func (a *App) writeStreamError(req *requestState, endpoint string, start time.Time, err error) {
	metrics.ProviderErrors.WithLabelValues(req.provider, errorType(err), req.product).Inc()
	metrics.RequestCount.WithLabelValues(endpoint, req.provider, req.model, strconv.Itoa(statusCode(err)), req.user.AuthMethod, req.product).Inc()
	metrics.RequestLatency.WithLabelValues(endpoint, req.provider, "true", req.product).Observe(time.Since(start).Seconds())
	a.posthog.CaptureAIGeneration(context.Background(), req.user, req.product, req.provider, req.model, captureInput(req), nil, ph.Usage{}, time.Since(start).Seconds(), true, req.endUserID, req.properties, req.flags, req.traceID, true, err.Error())
}

func statusCode(err error) int {
	var providerErr *llm.ProviderError
	if errors.As(err, &providerErr) && providerErr.StatusCode > 0 {
		return providerErr.StatusCode
	}
	return 500
}

func errorType(err error) string {
	var providerErr *llm.ProviderError
	if errors.As(err, &providerErr) && providerErr.Type != "" {
		return providerErr.Type
	}
	return "internal_error"
}

func redisFromSettings(ctx context.Context, settings *config.Settings) *redis.Client {
	if settings.RedisURL == "" {
		return nil
	}
	opts, err := redis.ParseURL(settings.RedisURL)
	if err != nil {
		log.Printf("redis_connection_failed: %v", err)
		return nil
	}
	client := redis.NewClient(opts)
	if err := client.Ping(ctx).Err(); err != nil {
		log.Printf("redis_connection_failed: %v", err)
		_ = client.Close()
		return nil
	}
	return client
}

func getState(r *http.Request) *requestState {
	state, _ := r.Context().Value(stateKey{}).(*requestState)
	if state == nil {
		state = &requestState{id: uuid.NewString()[:8]}
	}
	return state
}
func pathProduct(r *http.Request) string {
	if product := r.PathValue("product"); product != "" {
		return product
	}
	return "llm_gateway"
}
func providerFromHeaders(r *http.Request) (string, bool) {
	provider := strings.ToLower(r.Header.Get("X-PostHog-Provider"))
	if provider == "" {
		return "anthropic", true
	}
	return provider, provider == "anthropic" || provider == "bedrock"
}
func unsupportedModel(model string) bool {
	lower := strings.ToLower(model)
	return strings.HasPrefix(lower, "gemini/") || strings.HasPrefix(lower, "vertex_ai/") || strings.HasPrefix(lower, "vertex_ai-language-models/") || strings.HasPrefix(lower, "gemini-")
}
func endUserID(body map[string]any, user *auth.User) string {
	if user.AuthMethod == "oauth_access_token" {
		return strconv.Itoa(user.UserID)
	}
	if v, ok := body["user"].(string); ok {
		return v
	}
	if metadata, ok := body["metadata"].(map[string]any); ok {
		if v, ok := metadata["user_id"].(string); ok {
			return v
		}
	}
	return ""
}
func traceID(body map[string]any) string {
	if metadata, ok := body["metadata"].(map[string]any); ok {
		if v, ok := metadata["user_id"].(string); ok {
			return v
		}
	}
	return ""
}
func readLimited(body io.ReadCloser, limit int64) ([]byte, error) {
	defer body.Close()
	return io.ReadAll(http.MaxBytesReader(nil, body, limit))
}
func writeJSON(w http.ResponseWriter, status int, body any) {
	writeJSONWithHeaders(w, status, body, nil)
}
func writeJSONWithHeaders(w http.ResponseWriter, status int, body any, headers map[string]string) {
	for k, v := range headers {
		w.Header().Set(k, v)
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}
func writeError(w http.ResponseWriter, status int, message string, typ string, code any) {
	writeJSON(w, status, map[string]any{"error": map[string]any{"message": message, "type": typ, "code": code}})
}
func posthogProperties(headers http.Header) map[string]any {
	return prefixedHeaders(headers, "x-posthog-property-")
}
func posthogFlags(headers http.Header) map[string]any {
	return prefixedHeaders(headers, "x-posthog-flag-")
}
func prefixedHeaders(headers http.Header, prefix string) map[string]any {
	result := map[string]any{}
	for k, values := range headers {
		lower := strings.ToLower(k)
		if strings.HasPrefix(lower, prefix) && len(values) > 0 {
			result[strings.TrimPrefix(lower, prefix)] = values[0]
		}
	}
	return result
}
func extract(value any, key string) any {
	if m, ok := value.(map[string]any); ok {
		return m[key]
	}
	return nil
}

func captureInput(req *requestState) any {
	if messages := extract(req.input, "messages"); messages != nil {
		return messages
	}
	if input := extract(req.input, "input"); input != nil {
		return input
	}
	return req.input
}
func usageFromAnthropic(value any) llm.Usage {
	usage, _ := extract(value, "usage").(map[string]any)
	return llm.Usage{InputTokens: intNumber(usage["input_tokens"]), OutputTokens: intNumber(usage["output_tokens"])}
}
func intNumber(value any) int {
	if v, ok := value.(float64); ok {
		return int(v)
	}
	if v, ok := value.(int); ok {
		return v
	}
	return 0
}

func estimateCost(model string, provider string, inputTokens int, outputTokens int) float64 {
	type rate struct{ input, output float64 }
	rates := map[string]rate{
		"gpt-4.1-mini":      {0.0000004, 0.0000016},
		"gpt-4.1-nano":      {0.0000001, 0.0000004},
		"gpt-5-mini":        {0.00000025, 0.000002},
		"claude-haiku-4-5":  {0.0000008, 0.000004},
		"claude-sonnet-4-5": {0.000003, 0.000015},
		"claude-sonnet-4-6": {0.000003, 0.000015},
		"claude-opus-4-5":   {0.000015, 0.000075},
		"claude-opus-4-6":   {0.000015, 0.000075},
		"claude-opus-4-7":   {0.000015, 0.000075},
	}
	normalized := strings.TrimPrefix(strings.ToLower(model), provider+"/")
	for prefix, value := range rates {
		if strings.HasPrefix(normalized, prefix) {
			return float64(inputTokens)*value.input + float64(outputTokens)*value.output
		}
	}
	return 0
}
