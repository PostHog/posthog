package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/catalog"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/completion"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/serviceauth"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/validation"
)

type server struct {
	client       *catalog.Client
	defaultScope catalog.Scope
	catalogs     *catalog.Registry
	auth         *serviceauth.Authenticator
}

type completionRequest struct {
	TeamID   int64  `json:"teamId"`
	UserID   int64  `json:"userId"`
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
	TeamID int64  `json:"teamId"`
	UserID int64  `json:"userId"`
	Query  string `json:"query"`
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

	s := &server{catalogs: catalog.NewRegistry(maxCatalogs, catalogTTL), auth: serviceauth.New(keys, allowInsecure)}
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
		s.defaultScope.TeamID, err = strconv.ParseInt(projectID, 10, 64)
		if err != nil || s.defaultScope.TeamID <= 0 {
			fatalConfiguration(errors.New("POSTHOG_PROJECT_ID must be a positive team ID"))
		}
		s.defaultScope.UserID, err = strconv.ParseInt(userID, 10, 64)
		if err != nil || s.defaultScope.UserID <= 0 {
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
	mux.HandleFunc("PUT /teams/{teamID}/users/{userID}/catalog", s.putCatalog)
	mux.HandleFunc("DELETE /teams/{teamID}/users/{userID}/catalog", s.deleteCatalog)
	mux.HandleFunc("POST /teams/{teamID}/users/{userID}/reload", s.reloadHTTP)
	mux.HandleFunc("POST /autocomplete", s.autocomplete)
	mux.HandleFunc("POST /validate", s.validate)
	return mux
}

func (s *server) putCatalog(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromPath(w, r)
	if !ok || !s.authorize(w, r, scope, "publish") {
		return
	}
	var input catalogUpdate
	if !decodeJSON(w, r, 256<<20, &input) {
		return
	}
	if err := s.catalogs.Put(scope, input.Revision, &input.Catalog); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"teamId": scope.TeamID, "userId": scope.UserID, "revision": input.Revision})
}

func (s *server) deleteCatalog(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromPath(w, r)
	if !ok || !s.authorize(w, r, scope, "delete") {
		return
	}
	if !s.catalogs.Delete(scope) {
		http.Error(w, "catalog not found", http.StatusNotFound)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (s *server) autocomplete(w http.ResponseWriter, r *http.Request) {
	var input completionRequest
	if !decodeJSON(w, r, 1<<20, &input) {
		return
	}
	if input.TeamID <= 0 || input.UserID <= 0 {
		http.Error(w, "teamId and userId must be positive integers", http.StatusBadRequest)
		return
	}
	scope := catalog.Scope{TeamID: input.TeamID, UserID: input.UserID}
	if !s.authorize(w, r, scope, "complete") {
		return
	}
	current, revision, ok := s.catalogs.Get(scope)
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

func (s *server) validate(w http.ResponseWriter, r *http.Request) {
	var input validationRequest
	if !decodeJSON(w, r, 1<<20, &input) {
		return
	}
	if input.TeamID <= 0 || input.UserID <= 0 {
		http.Error(w, "teamId and userId must be positive integers", http.StatusBadRequest)
		return
	}
	scope := catalog.Scope{TeamID: input.TeamID, UserID: input.UserID}
	if !s.authorize(w, r, scope, "validate") {
		return
	}
	current, revision, ok := s.catalogs.Get(scope)
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
	return s.catalogs.Put(s.defaultScope, strconv.FormatInt(time.Now().UnixNano(), 10), next)
}

func (s *server) reloadHTTP(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromPath(w, r)
	if !ok || !s.authorize(w, r, scope, "publish") {
		return
	}
	if s.client == nil || scope != s.defaultScope {
		http.Error(w, "team loader not configured", http.StatusNotFound)
		return
	}
	if err := s.reloadDefault(r.Context()); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	current, revision, _ := s.catalogs.Get(scope)
	writeJSON(w, http.StatusOK, map[string]any{"teamId": scope.TeamID, "userId": scope.UserID, "revision": revision, "tables": len(current.Tables), "properties": propertyCount(current)})
}

func (s *server) health(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func (s *server) authorize(w http.ResponseWriter, r *http.Request, scope catalog.Scope, operation string) bool {
	if err := s.auth.Verify(r.Header.Get("Authorization"), scope.TeamID, scope.UserID, operation); err != nil {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return false
	}
	return true
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

func scopeFromPath(w http.ResponseWriter, r *http.Request) (catalog.Scope, bool) {
	teamID, err := strconv.ParseInt(r.PathValue("teamID"), 10, 64)
	if err != nil {
		http.Error(w, "teamID and userID must be positive integers", http.StatusBadRequest)
		return catalog.Scope{}, false
	}
	userID, err := strconv.ParseInt(r.PathValue("userID"), 10, 64)
	if err != nil || teamID <= 0 || userID <= 0 {
		http.Error(w, "teamID and userID must be positive integers", http.StatusBadRequest)
		return catalog.Scope{}, false
	}
	return catalog.Scope{TeamID: teamID, UserID: userID}, true
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
