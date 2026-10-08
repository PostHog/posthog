package main

import (
	"bytes"
	"context"
	"embed"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"io/fs"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/catalog"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/httpapi"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/ratelimit"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/serviceauth"
)

// Embedding only in this command keeps the demo out of the production server binary.
//
//go:embed assets/*
var assets embed.FS

func newDemoHandler(host string) (http.Handler, error) {
	publication := syntheticCatalog()
	payload, err := json.Marshal(publication)
	if err != nil {
		return nil, err
	}
	catalogs := catalog.NewRegistry(1, 16<<20, 24*time.Hour)
	if err := catalogs.Put(serviceauth.Authorization{TeamID: 1, UserID: 1}, publication.Revision, catalog.Prepare(&publication.Catalog)); err != nil {
		return nil, err
	}
	preAuthLimiter, err := ratelimit.New(ratelimit.Config{Capacity: 300, RefillPerSec: 100, MaxEntries: 10000, IdleTTL: 10 * time.Minute})
	if err != nil {
		return nil, err
	}
	principalLimiter, err := ratelimit.New(ratelimit.Config{Capacity: 120, RefillPerSec: 60, MaxEntries: 10000, IdleTTL: 10 * time.Minute})
	if err != nil {
		return nil, err
	}
	backend := httpapi.NewHandler(httpapi.Config{
		Catalogs:         catalogs,
		Auth:             serviceauth.New(nil, true),
		PreAuthLimiter:   preAuthLimiter,
		PrincipalLimiter: principalLimiter,
		Logger:           slog.Default(),
	})
	return demoHandler(backend, host, payload), nil
}

func demoHandler(backend http.Handler, host string, payload []byte) http.Handler {
	static, _ := fs.Sub(assets, "assets")
	mux := http.NewServeMux()
	mux.Handle("GET /", http.FileServer(http.FS(static)))
	mux.HandleFunc("GET /api/catalog", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		// The payload is the JSON-encoded synthetic catalog; application/json and nosniff prevent HTML interpretation.
		// nosemgrep: go.lang.security.audit.xss.no-direct-write-to-responsewriter.no-direct-write-to-responsewriter
		_, _ = w.Write(payload)
	})
	mux.HandleFunc("GET /api/health", func(w http.ResponseWriter, r *http.Request) {
		request, err := http.NewRequestWithContext(r.Context(), http.MethodGet, "/health", nil)
		if err != nil {
			http.Error(w, "Could not check the service. Restart the demo.", http.StatusInternalServerError)
			return
		}
		request.RemoteAddr = r.RemoteAddr
		backend.ServeHTTP(w, request)
	})
	for _, operation := range []string{"autocomplete", "validate"} {
		mux.HandleFunc("POST /api/"+operation, func(w http.ResponseWriter, r *http.Request) {
			body, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 128<<10))
			if err != nil {
				http.Error(w, "Request too large. Use a shorter query.", http.StatusRequestEntityTooLarge)
				return
			}
			request, err := http.NewRequestWithContext(r.Context(), http.MethodPost, "/teams/1/users/1/"+operation, bytes.NewReader(body))
			if err != nil {
				http.Error(w, "Could not create request. Restart the demo.", http.StatusInternalServerError)
				return
			}
			request.Header.Set("Content-Type", "application/json")
			request.RemoteAddr = r.RemoteAddr
			backend.ServeHTTP(w, request)
		})
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Cache-Control", "no-store")
		origin := r.Header.Get("Origin")
		if (host != "" && r.Host != host) || (origin != "" && origin != "http://"+r.Host && origin != "https://"+r.Host) {
			http.Error(w, "Send requests from the demo page's own address.", http.StatusForbidden)
			return
		}
		if r.Method == http.MethodPost && !strings.HasPrefix(r.Header.Get("Content-Type"), "application/json") {
			http.Error(w, "Send JSON requests from the demo page.", http.StatusUnsupportedMediaType)
			return
		}
		mux.ServeHTTP(w, r)
	})
}

func run(ctx context.Context, host string, port int) error {
	listener, err := net.Listen("tcp", net.JoinHostPort(host, fmt.Sprint(port)))
	if err != nil {
		return err
	}
	defer listener.Close()
	allowedHost := listener.Addr().String()
	if ip := net.ParseIP(host); ip != nil && ip.IsUnspecified() {
		allowedHost = ""
	}
	handler, err := newDemoHandler(allowedHost)
	if err != nil {
		return err
	}
	server := &http.Server{
		Handler:           handler,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      10 * time.Second,
		IdleTimeout:       60 * time.Second,
	}
	go func() {
		<-ctx.Done()
		_ = server.Close()
	}()
	fmt.Printf("\nHogQL demo: http://%s\nSynthetic catalog only. Queries are not executed. Press Ctrl+C to stop.\n\n", listener.Addr())
	err = server.Serve(listener)
	if errors.Is(err, http.ErrServerClosed) {
		return nil
	}
	return err
}

func main() {
	host := flag.String("host", "127.0.0.1", "bind address; use 0.0.0.0 for port forwarding")
	port := flag.Int("port", 8092, "port for the demo page")
	flag.Parse()
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	if err := run(ctx, *host, *port); err != nil && !errors.Is(err, context.Canceled) {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
