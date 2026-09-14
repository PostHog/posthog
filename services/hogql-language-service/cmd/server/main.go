package main

import (
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
	maxCatalogs, err := positiveIntEnv("MAX_CATALOGS", 1024)
	if err != nil {
		fatalConfiguration(err)
	}
	catalogTTL, err := positiveDurationEnv("CATALOG_TTL", 30*time.Minute)
	if err != nil {
		fatalConfiguration(err)
	}
	maxCatalogBytes, err := positiveIntEnv("CATALOG_CACHE_MAX_BYTES", 8<<30)
	if err != nil {
		fatalConfiguration(err)
	}
	keys := splitNonEmpty(os.Getenv("HOGQL_LANGUAGE_SERVICE_SIGNING_KEYS"))
	allowInsecure, err := allowInsecureAuthentication(listenAddress, os.Getenv("HOGQL_LANGUAGE_SERVICE_ALLOW_INSECURE"))
	if err != nil {
		fatalConfiguration(err)
	}
	if len(keys) == 0 && !allowInsecure {
		fatalConfiguration(errors.New("HOGQL_LANGUAGE_SERVICE_SIGNING_KEYS is required"))
	}
	if allowInsecure {
		slog.Warn("authentication disabled for local development", "address", listenAddress)
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
		catalogs:         catalog.NewRegistry(maxCatalogs, int64(maxCatalogBytes), catalogTTL),
		auth:             serviceauth.New(keys, allowInsecure),
		preAuthLimiter:   configuredLimiter("PRE_AUTH_RATE_LIMIT", 300, 100, maxRateLimitKeys, rateLimitIdleTTL),
		principalLimiter: configuredLimiter("PRINCIPAL_RATE_LIMIT", 120, 60, maxRateLimitKeys, rateLimitIdleTTL),
	}
	httpServer := &http.Server{
		Addr:              listenAddress,
		Handler:           s.handler(),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       30 * time.Second,
		WriteTimeout:      30 * time.Second,
		IdleTimeout:       60 * time.Second,
	}
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
	mux.Handle("POST /teams/{teamID}/users/{userID}/autocomplete", s.authorized(serviceauth.OperationComplete, s.autocomplete))
	mux.Handle("POST /teams/{teamID}/users/{userID}/validate", s.authorized(serviceauth.OperationValidate, s.validate))
	return securityHeaders(mux)
}

func securityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Content-Type-Options", "nosniff")
		next.ServeHTTP(w, r)
	})
}

type authorizedHandler func(http.ResponseWriter, *http.Request, serviceauth.Authorization)

func (s *server) authorized(operation serviceauth.Operation, next authorizedHandler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		preAuthAllowed, retryAfter := s.preAuthLimiter.Allow(remoteAddress(r))
		authorization, err := authorizationFromPath(r)
		if err != nil {
			if !preAuthAllowed {
				writeRateLimitResponse(w, retryAfter)
			} else {
				http.Error(w, err.Error(), http.StatusBadRequest)
			}
			return
		}
		if err := s.auth.Verify(r.Header.Get("Authorization"), authorization, operation); err != nil {
			if !preAuthAllowed {
				writeRateLimitResponse(w, retryAfter)
			} else {
				http.Error(w, "unauthorized", http.StatusUnauthorized)
			}
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
	if !decodeJSON(w, r, 64<<20, &input) {
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
	if !decodeJSON(w, r, 128<<10, &input) {
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
	if !decodeJSON(w, r, 128<<10, &input) {
		return
	}
	current, revision, ok := s.catalogs.Get(authorization)
	if !ok {
		http.Error(w, "catalog not found", http.StatusNotFound)
		return
	}
	writeJSON(w, http.StatusOK, validationResponse{Result: validation.Validate(current, input.Query), CatalogRevision: revision})
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

func authorizationFromPath(r *http.Request) (serviceauth.Authorization, error) {
	teamID, err := strconv.ParseInt(r.PathValue("teamID"), 10, 64)
	if err != nil {
		return serviceauth.Authorization{}, errors.New("teamID and userID must be positive integers")
	}
	userID, err := strconv.ParseInt(r.PathValue("userID"), 10, 64)
	if err != nil || teamID <= 0 || userID <= 0 {
		return serviceauth.Authorization{}, errors.New("teamID and userID must be positive integers")
	}
	return serviceauth.Authorization{TeamID: teamID, UserID: userID}, nil
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
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Content-Length", strconv.Itoa(len(body)))
	w.WriteHeader(status)
	// nosemgrep: go.lang.security.audit.xss.no-direct-write-to-responsewriter.no-direct-write-to-responsewriter -- json.Marshal escapes strings and this response has an application/json content type.
	if _, err := w.Write(body); err != nil {
		slog.Warn("write response", "error", err)
	}
}

func allowInsecureAuthentication(listenAddress, configured string) (bool, error) {
	if configured != "1" {
		return false, nil
	}
	if !isLoopbackAddress(listenAddress) {
		return false, errors.New("HOGQL_LANGUAGE_SERVICE_ALLOW_INSECURE requires a loopback LISTEN_ADDR")
	}
	return true, nil
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
