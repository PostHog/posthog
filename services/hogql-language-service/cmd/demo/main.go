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
	"net"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"
)

// Embedding only in this command keeps the demo out of the production server binary.
//
//go:embed assets/*
var assets embed.FS

const catalogPath = "/teams/1/users/1/catalog"

func startBackend(ctx context.Context) (string, func(), error) {
	directory, err := os.MkdirTemp("", "hogql-demo-")
	if err != nil {
		return "", nil, err
	}
	cleanup := func() { _ = os.RemoveAll(directory) }
	binary := filepath.Join(directory, "language-service")
	build := exec.CommandContext(ctx, "go", "build", "-o", binary, "./cmd/server")
	build.Stdout, build.Stderr = os.Stdout, os.Stderr
	if err := build.Run(); err != nil {
		cleanup()
		return "", nil, fmt.Errorf("build service (run from the language-service module): %w", err)
	}
	reservation, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		cleanup()
		return "", nil, err
	}
	address := reservation.Addr().String()
	_ = reservation.Close()
	backendCtx, cancel := context.WithCancel(ctx)
	// The executable is built from this checkout in a private temporary directory, with no request-controlled path.
	// nosemgrep: go.lang.security.audit.dangerous-exec-command.dangerous-exec-command
	child := exec.CommandContext(backendCtx, binary)
	child.Env = []string{
		"LISTEN_ADDR=" + address,
		"HOGQL_LANGUAGE_SERVICE_ALLOW_INSECURE=1",
		"CATALOG_TTL=24h",
		"MAX_CATALOGS=1",
		"CATALOG_CACHE_MAX_BYTES=16777216",
	}
	child.Stdout, child.Stderr = os.Stdout, os.Stderr
	if err := child.Start(); err != nil {
		cancel()
		cleanup()
		return "", nil, err
	}
	done := make(chan struct{})
	go func() {
		_ = child.Wait()
		close(done)
	}()
	stop := func() {
		cancel()
		<-done
		cleanup()
	}
	baseURL := "http://" + address
	client := &http.Client{Timeout: time.Second}
	ticker := time.NewTicker(50 * time.Millisecond)
	defer ticker.Stop()
	timeout := time.NewTimer(10 * time.Second)
	defer timeout.Stop()
	for {
		select {
		case <-ctx.Done():
			stop()
			return "", nil, ctx.Err()
		case <-done:
			stop()
			return "", nil, errors.New("demo backend exited; check its output above")
		case <-timeout.C:
			stop()
			return "", nil, errors.New("demo backend did not become ready")
		case <-ticker.C:
			response, err := client.Get(baseURL + "/health")
			if err == nil {
				_ = response.Body.Close()
				if response.StatusCode == http.StatusOK {
					return baseURL, stop, nil
				}
			}
		}
	}
}

func publishCatalog(ctx context.Context, baseURL string, payload []byte) error {
	request, err := http.NewRequestWithContext(ctx, http.MethodPut, baseURL+catalogPath, bytes.NewReader(payload))
	if err != nil {
		return err
	}
	request.Header.Set("Content-Type", "application/json")
	response, err := (&http.Client{Timeout: 5 * time.Second}).Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("catalog publication returned HTTP %d", response.StatusCode)
	}
	return nil
}

func demoHandler(baseURL, host string, payload []byte) http.Handler {
	static, _ := fs.Sub(assets, "assets")
	mux := http.NewServeMux()
	mux.Handle("GET /", http.FileServer(http.FS(static)))
	mux.HandleFunc("GET /api/catalog", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		// The payload is the JSON-encoded synthetic catalog; application/json and nosniff prevent HTML interpretation.
		// nosemgrep: go.lang.security.audit.xss.no-direct-write-to-responsewriter.no-direct-write-to-responsewriter
		_, _ = w.Write(payload)
	})
	client := &http.Client{Timeout: 5 * time.Second}
	for _, operation := range []string{"autocomplete", "validate"} {
		mux.HandleFunc("POST /api/"+operation, func(w http.ResponseWriter, r *http.Request) {
			body, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 128<<10))
			if err != nil {
				http.Error(w, "Request too large. Use a shorter query.", http.StatusRequestEntityTooLarge)
				return
			}
			request, err := http.NewRequestWithContext(r.Context(), http.MethodPost, baseURL+"/teams/1/users/1/"+operation, bytes.NewReader(body))
			if err != nil {
				http.Error(w, "Could not create request. Restart the demo.", http.StatusInternalServerError)
				return
			}
			request.Header.Set("Content-Type", "application/json")
			response, err := client.Do(request)
			if err != nil {
				http.Error(w, "The local service is unavailable. Restart the demo.", http.StatusBadGateway)
				return
			}
			defer response.Body.Close()
			w.Header().Set("Content-Type", response.Header.Get("Content-Type"))
			w.WriteHeader(response.StatusCode)
			_, _ = io.Copy(w, response.Body)
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
	fmt.Println("Building a separate local language service...")
	baseURL, stop, err := startBackend(ctx)
	if err != nil {
		return err
	}
	defer stop()
	payload, err := json.Marshal(syntheticCatalog())
	if err != nil {
		return err
	}
	if err := publishCatalog(ctx, baseURL, payload); err != nil {
		return err
	}
	allowedHost := listener.Addr().String()
	if ip := net.ParseIP(host); ip != nil && ip.IsUnspecified() {
		allowedHost = ""
	}
	server := &http.Server{
		Handler:           demoHandler(baseURL, allowedHost, payload),
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
