package server

import (
	"github.com/maximhq/bifrost/core/schemas"
	"github.com/posthog/posthog/services/llm-gateway/internal/llm"
	"github.com/posthog/posthog/services/llm-gateway/internal/metrics"
	"github.com/posthog/posthog/services/llm-gateway/internal/products"
	"io"
	"mime/multipart"
	"net/http"
	"time"
)

func (a *App) chatCompletions(w http.ResponseWriter, r *http.Request) {
	raw, req, ok := a.prepareJSONRequest(w, r, "chat_completions", []string{"model", "messages"})
	if !ok {
		return
	}
	provider, parsedModel := llm.ProviderFromModel(req.model, schemas.OpenAI)
	req.provider = string(provider)
	start := time.Now()
	metrics.ConcurrentRequests.WithLabelValues(req.provider, req.model, req.product).Inc()
	defer metrics.ConcurrentRequests.WithLabelValues(req.provider, req.model, req.product).Dec()
	if req.stream {
		stream, errs, err := a.llm.ChatCompletionStream(r.Context(), raw, parsedModel, provider, r.Header)
		if err != nil {
			a.writeProviderError(w, err, req, "chat_completions", start, true)
			return
		}
		a.writeStream(w, stream, errs, req, "chat_completions", start)
		return
	}
	resp, err := a.llm.ChatCompletion(r.Context(), raw, parsedModel, provider, false, r.Header)
	if err != nil {
		a.writeProviderError(w, err, req, "chat_completions", start, false)
		return
	}
	a.afterSuccess(r.Context(), req, "chat_completions", start, false, resp)
	writeJSON(w, 200, resp.Body)
}

func (a *App) responses(w http.ResponseWriter, r *http.Request) {
	raw, req, ok := a.prepareJSONRequest(w, r, "responses", []string{"model", "input"})
	if !ok {
		return
	}
	start := time.Now()
	metrics.ConcurrentRequests.WithLabelValues("openai", req.model, req.product).Inc()
	defer metrics.ConcurrentRequests.WithLabelValues("openai", req.model, req.product).Dec()
	if req.stream {
		stream, errs, err := a.llm.ResponsesStream(r.Context(), raw, req.model, r.Header)
		if err != nil {
			a.writeProviderError(w, err, req, "responses", start, true)
			return
		}
		a.writeStream(w, stream, errs, req, "responses", start)
		return
	}
	resp, err := a.llm.Responses(r.Context(), raw, req.model, false, r.Header)
	if err != nil {
		a.writeProviderError(w, err, req, "responses", start, false)
		return
	}
	req.provider = "openai"
	a.afterSuccess(r.Context(), req, "responses", start, false, resp)
	writeJSON(w, 200, resp.Body)
}

func (a *App) transcriptions(w http.ResponseWriter, r *http.Request) {
	req, ok := a.authenticateOnly(w, r)
	if !ok {
		return
	}
	if err := r.ParseMultipartForm(26 << 20); err != nil {
		writeError(w, 400, "Invalid multipart form", "invalid_request_error", nil)
		return
	}
	file, header, err := r.FormFile("file")
	if err != nil {
		writeError(w, 400, "File must have a filename", "invalid_request_error", nil)
		return
	}
	defer file.Close()
	content, err := io.ReadAll(io.LimitReader(file, 25*1024*1024+1))
	if err != nil {
		writeError(w, 400, "Could not read file", "invalid_request_error", nil)
		return
	}
	if len(content) > 25*1024*1024 {
		writeError(w, 413, "File size exceeds maximum allowed size of 25MB", "invalid_request_error", nil)
		return
	}
	model := formValue(r.MultipartForm, "model", "gpt-4o-transcribe")
	req.model = llm.EnsureOpenAIPrefix(model)
	req.provider = "openai"
	if allowed, msg := products.CheckAccess(a.settings, req.product, req.user, model, "openai"); !allowed {
		writeError(w, 403, msg, "permission_error", nil)
		return
	}
	start := time.Now()
	resp, err := a.llm.Transcription(r.Context(), header.Filename, header.Header.Get("Content-Type"), content, req.model, formValue(r.MultipartForm, "language", ""))
	if err != nil {
		a.writeProviderError(w, err, req, "audio_transcriptions", start, false)
		return
	}
	a.afterSuccess(r.Context(), req, "audio_transcriptions", start, false, resp)
	writeJSON(w, 200, resp.Body)
}

func formValue(form *multipart.Form, key string, fallback string) string {
	if form == nil {
		return fallback
	}
	if values := form.Value[key]; len(values) > 0 {
		return values[0]
	}
	return fallback
}
