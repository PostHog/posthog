package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"math"
	"net"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/catalog"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/completion"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/ratelimit"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/serviceauth"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/validation"
)

type server struct {
	client           *catalog.Client
	defaultAuth      serviceauth.Authorization
	catalogs         *catalog.Registry
	auth             *serviceauth.Authenticator
	preAuthLimiter   *ratelimit.Limiter
	principalLimiter *ratelimit.Limiter
}

type completionRequest struct {
	Query    string `json:"query"`
	Position *int   `json:"position,omitempty"`
	Cursor   string `json:"cursor,omitempty"`
}

type completionResponse struct {
	completion.Result
	CatalogRevision string `json:"catalogRevision"`
	DurationMicros  int64  `json:"durationMicros"`
}

type validationRequest struct {
	Query string `json:"query"`
}

type validationResponse struct {
	validation.Result
	CatalogRevision string `json:"catalogRevision"`
}

type catalogUpdate struct {
	Revision string          `json:"revision"`
	Catalog  catalog.Catalog `json:"catalog"`
}

func main() {
	listenAddress := env("LISTEN_ADDR", "127.0.0.1:8091")
	maxCatalogs, err := positiveIntEnv("MAX_CATALOGS", 256)
	if err != nil {
		fatalConfiguration(err)
	}
	catalogTTL, err := positiveDurationEnv("CATALOG_TTL", 30*time.Minute)
	if err != nil {
		fatalConfiguration(err)
	}
	keys := splitNonEmpty(os.Getenv("HOGQL_LANGUAGE_SERVICE_SIGNING_KEYS"))
	allowInsecure := len(keys) == 0 && isLoopbackAddress(listenAddress)
	if len(keys) == 0 && !allowInsecure {
		fatalConfiguration(errors.New("HOGQL_LANGUAGE_SERVICE_SIGNING_KEYS is required when LISTEN_ADDR is not loopback"))
	}
	maxRateLimitKeys, err := positiveIntEnv("RATE_LIMIT_MAX_KEYS", 10000)
	if err != nil {
		fatalConfiguration(err)
	}
	rateLimitIdleTTL, err := positiveDurationEnv("RATE_LIMIT_IDLE_TTL", 10*time.Minute)
	if err != nil {
		fatalConfiguration(err)
	}

	s := &server{
		catalogs:         catalog.NewRegistry(maxCatalogs, catalogTTL),
		auth:             serviceauth.New(keys, allowInsecure),
		preAuthLimiter:   configuredLimiter("PRE_AUTH_RATE_LIMIT", 300, 100, maxRateLimitKeys, rateLimitIdleTTL),
		principalLimiter: configuredLimiter("PRINCIPAL_RATE_LIMIT", 120, 60, maxRateLimitKeys, rateLimitIdleTTL),
	}
	projectID := os.Getenv("POSTHOG_PROJECT_ID")
	userID := os.Getenv("POSTHOG_USER_ID")
	personalAPIKey := os.Getenv("POSTHOG_PERSONAL_API_KEY")
	configuredBootstrapValues := 0
	for _, value := range []string{projectID, userID, personalAPIKey} {
		if value != "" {
			configuredBootstrapValues++
		}
	}
	if configuredBootstrapValues != 0 && configuredBootstrapValues != 3 {
		fatalConfiguration(errors.New("POSTHOG_PROJECT_ID, POSTHOG_USER_ID, and POSTHOG_PERSONAL_API_KEY must be set together"))
	}
	if projectID != "" {
		s.defaultAuth.TeamID, err = strconv.ParseInt(projectID, 10, 64)
		if err != nil || s.defaultAuth.TeamID <= 0 {
			fatalConfiguration(errors.New("POSTHOG_PROJECT_ID must be a positive team ID"))
		}
		s.defaultAuth.UserID, err = strconv.ParseInt(userID, 10, 64)
		if err != nil || s.defaultAuth.UserID <= 0 {
			fatalConfiguration(errors.New("POSTHOG_USER_ID must be a positive user ID"))
		}
		s.client, err = catalog.NewClient(env("POSTHOG_BASE_URL", "http://localhost:8010"), projectID, personalAPIKey, &http.Client{Timeout: 30 * time.Second})
		if err != nil {
			fatalConfiguration(err)
		}
		if err := s.reloadDefault(context.Background()); err != nil {
			slog.Error("initial catalog load failed", "error", err)
			os.Exit(1)
		}
	}

	httpServer := &http.Server{Addr: listenAddress, Handler: s.handler(), ReadHeaderTimeout: 5 * time.Second}
	stats := s.catalogs.Stats()
	slog.Info("HogQL language service listening", "address", listenAddress, "catalogs", stats.Catalogs, "tables", stats.Tables, "properties", stats.Properties)
	if err := httpServer.ListenAndServe(); !errors.Is(err, http.ErrServerClosed) {
		slog.Error("server stopped", "error", err)
		os.Exit(1)
	}
}

func (s *server) handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", s.health)
	mux.Handle("PUT /teams/{teamID}/users/{userID}/catalog", s.authorized(serviceauth.OperationPublish, s.putCatalog))
	mux.Handle("DELETE /teams/{teamID}/users/{userID}/catalog", s.authorized(serviceauth.OperationDelete, s.deleteCatalog))
	mux.Handle("POST /teams/{teamID}/users/{userID}/reload", s.authorized(serviceauth.OperationPublish, s.reloadHTTP))
	mux.Handle("POST /teams/{teamID}/users/{userID}/autocomplete", s.authorized(serviceauth.OperationComplete, s.autocomplete))
	mux.Handle("POST /teams/{teamID}/users/{userID}/validate", s.authorized(serviceauth.OperationValidate, s.validate))
	return mux
}

type authorizedHandler func(http.ResponseWriter, *http.Request, serviceauth.Authorization)

func (s *server) authorized(operation serviceauth.Operation, next authorizedHandler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if allowed, retryAfter := s.preAuthLimiter.Allow(remoteAddress(r)); !allowed {
			writeRateLimitResponse(w, retryAfter)
			return
		}
		authorization, ok := authorizationFromPath(w, r)
		if !ok {
			return
		}
		if err := s.auth.Verify(r.Header.Get("Authorization"), authorization, operation); err != nil {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		if allowed, retryAfter := s.principalLimiter.Allow(authorizationKey(authorization)); !allowed {
			writeRateLimitResponse(w, retryAfter)
			return
		}
		next(w, r, authorization)
	})
}

func (s *server) putCatalog(w http.ResponseWriter, r *http.Request, authorization serviceauth.Authorization) {
	var input catalogUpdate
	if !decodeJSON(w, r, 256<<20, &input) {
		return
	}
	if err := s.catalogs.Put(authorization, input.Revision, &input.Catalog); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"teamId": authorization.TeamID, "userId": authorization.UserID, "revision": input.Revision})
}

func (s *server) deleteCatalog(w http.ResponseWriter, _ *http.Request, authorization serviceauth.Authorization) {
	if !s.catalogs.Delete(authorization) {
		http.Error(w, "catalog not found", http.StatusNotFound)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (s *server) autocomplete(w http.ResponseWriter, r *http.Request, authorization serviceauth.Authorization) {
	var input completionRequest
	if !decodeJSON(w, r, 1<<20, &input) {
		return
	}
	current, revision, ok := s.catalogs.Get(authorization)
	if !ok {
		http.Error(w, "catalog not found", http.StatusNotFound)
		return
	}
	position := len(input.Query)
	if input.Position != nil {
		position = *input.Position
	}
	started := time.Now()
	result, err := completion.Complete(current, input.Query, position, input.Cursor)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	writeJSON(w, http.StatusOK, completionResponse{Result: result, CatalogRevision: revision, DurationMicros: time.Since(started).Microseconds()})
}

func (s *server) validate(w http.ResponseWriter, r *http.Request, authorization serviceauth.Authorization) {
	var input validationRequest
	if !decodeJSON(w, r, 1<<20, &input) {
		return
	}
	current, revision, ok := s.catalogs.Get(authorization)
	if !ok {
		http.Error(w, "catalog not found", http.StatusNotFound)
		return
	}
	writeJSON(w, http.StatusOK, validationResponse{Result: validation.Validate(current, input.Query), CatalogRevision: revision})
}

func (s *server) reloadDefault(ctx context.Context) error {
	if s.client == nil {
		return errors.New("team and user catalog loader is not configured")
	}
	next, err := s.client.Load(ctx)
	if err != nil {
		return err
	}
	return s.catalogs.Put(s.defaultAuth, strconv.FormatInt(time.Now().UnixNano(), 10), next)
}

func (s *server) reloadHTTP(w http.ResponseWriter, r *http.Request, authorization serviceauth.Authorization) {
	if s.client == nil || authorization != s.defaultAuth {
		http.Error(w, "team loader not configured", http.StatusNotFound)
		return
	}
	if err := s.reloadDefault(r.Context()); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	current, revision, _ := s.catalogs.Get(authorization)
	writeJSON(w, http.StatusOK, map[string]any{"teamId": authorization.TeamID, "userId": authorization.UserID, "revision": revision, "tables": len(current.Tables), "properties": propertyCount(current)})
}

func (s *server) health(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func decodeJSON(w http.ResponseWriter, r *http.Request, maxBytes int64, target any) bool {
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, maxBytes))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		http.Error(w, "invalid request: "+err.Error(), http.StatusBadRequest)
		return false
	}
	return true
}

func propertyCount(current *catalog.Catalog) int {
	count := 0
	for _, properties := range current.Properties {
		count += len(properties)
	}
	return count
}

func authorizationFromPath(w http.ResponseWriter, r *http.Request) (serviceauth.Authorization, bool) {
	teamID, err := strconv.ParseInt(r.PathValue("teamID"), 10, 64)
	if err != nil {
		http.Error(w, "teamID and userID must be positive integers", http.StatusBadRequest)
		return serviceauth.Authorization{}, false
	}
	userID, err := strconv.ParseInt(r.PathValue("userID"), 10, 64)
	if err != nil || teamID <= 0 || userID <= 0 {
		http.Error(w, "teamID and userID must be positive integers", http.StatusBadRequest)
		return serviceauth.Authorization{}, false
	}
	return serviceauth.Authorization{TeamID: teamID, UserID: userID}, true
}

func remoteAddress(r *http.Request) string {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}

func authorizationKey(authorization serviceauth.Authorization) string {
	return strconv.FormatInt(authorization.TeamID, 10) + ":" + strconv.FormatInt(authorization.UserID, 10)
}

func writeRateLimitResponse(w http.ResponseWriter, retryAfter time.Duration) {
	seconds := max(int64(1), int64((retryAfter+time.Second-1)/time.Second))
	w.Header().Set("Retry-After", strconv.FormatInt(seconds, 10))
	http.Error(w, "rate limit exceeded", http.StatusTooManyRequests)
}

func isLoopbackAddress(address string) bool {
	host, _, err := net.SplitHostPort(address)
	if err != nil {
		return false
	}
	return host == "localhost" || net.ParseIP(host).IsLoopback()
}

func splitNonEmpty(value string) []string {
	var values []string
	for _, item := range strings.Split(value, ",") {
		if item = strings.TrimSpace(item); item != "" {
			values = append(values, item)
		}
	}
	return values
}

func positiveIntEnv(name string, fallback int) (int, error) {
	value := os.Getenv(name)
	if value == "" {
		return fallback, nil
	}
	parsed, err := strconv.Atoi(value)
	if err != nil || parsed <= 0 {
		return 0, fmt.Errorf("%s must be a positive integer", name)
	}
	return parsed, nil
}

func positiveDurationEnv(name string, fallback time.Duration) (time.Duration, error) {
	value := os.Getenv(name)
	if value == "" {
		return fallback, nil
	}
	parsed, err := time.ParseDuration(value)
	if err != nil || parsed <= 0 {
		return 0, fmt.Errorf("%s must be a positive duration", name)
	}
	return parsed, nil
}

func configuredLimiter(prefix string, defaultCapacity, defaultRefill float64, maxEntries int, idleTTL time.Duration) *ratelimit.Limiter {
	capacity, err := positiveFloatEnv(prefix+"_CAPACITY", defaultCapacity)
	if err != nil {
		fatalConfiguration(err)
	}
	refill, err := positiveFloatEnv(prefix+"_REFILL_PER_SECOND", defaultRefill)
	if err != nil {
		fatalConfiguration(err)
	}
	limiter, err := ratelimit.New(ratelimit.Config{Capacity: capacity, RefillPerSec: refill, MaxEntries: maxEntries, IdleTTL: idleTTL})
	if err != nil {
		fatalConfiguration(err)
	}
	return limiter
}

func positiveFloatEnv(name string, fallback float64) (float64, error) {
	value := os.Getenv(name)
	if value == "" {
		return fallback, nil
	}
	parsed, err := strconv.ParseFloat(value, 64)
	if err != nil || parsed <= 0 || math.IsNaN(parsed) || math.IsInf(parsed, 0) {
		return 0, fmt.Errorf("%s must be a positive number", name)
	}
	return parsed, nil
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	body, err := json.Marshal(value)
	if err != nil {
		http.Error(w, "encode response", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if _, err := w.Write(body); err != nil {
		slog.Warn("write response", "error", err)
	}
}

func fatalConfiguration(err error) {
	slog.Error("invalid configuration", "error", err)
	os.Exit(1)
}

func env(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}
