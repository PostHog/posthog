package main

import (
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
	"github.com/PostHog/posthog/services/hogql-language-service/internal/httpapi"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/ratelimit"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/serviceauth"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	slog.SetDefault(logger)
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

	catalogs := catalog.NewRegistry(maxCatalogs, int64(maxCatalogBytes), catalogTTL)
	handler := httpapi.NewHandler(httpapi.Config{
		Catalogs:         catalogs,
		Auth:             serviceauth.New(keys, allowInsecure),
		PreAuthLimiter:   configuredLimiter("PRE_AUTH_RATE_LIMIT", 300, 100, maxRateLimitKeys, rateLimitIdleTTL),
		PrincipalLimiter: configuredLimiter("PRINCIPAL_RATE_LIMIT", 120, 60, maxRateLimitKeys, rateLimitIdleTTL),
		Logger:           logger,
	})
	httpServer := &http.Server{
		Addr:              listenAddress,
		Handler:           handler,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       30 * time.Second,
		WriteTimeout:      30 * time.Second,
		IdleTimeout:       60 * time.Second,
	}
	stats := catalogs.Stats()
	slog.Info("HogQL language service listening", "address", listenAddress, "catalogs", stats.Catalogs, "tables", stats.Tables, "properties", stats.Properties)
	if err := httpServer.ListenAndServe(); !errors.Is(err, http.ErrServerClosed) {
		slog.Error("server stopped", "error", err)
		os.Exit(1)
	}
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
