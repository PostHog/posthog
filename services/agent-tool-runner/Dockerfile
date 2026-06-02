# syntax=docker/dockerfile:1
# Multi-stage build for posthog-tool-runner. Final image is a distroless
# static base — single static binary, ~10MB image, no shell, no package
# manager. Customers pull this from a public registry.

FROM golang:1.25-alpine AS build
WORKDIR /src
ARG VERSION=dev

# Cache module downloads as a separate layer so source-only changes don't
# bust them.
COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build \
    -ldflags "-s -w -X main.Version=${VERSION}" \
    -o /out/posthog-tool-runner .

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/posthog-tool-runner /usr/local/bin/posthog-tool-runner
USER nonroot:nonroot
ENTRYPOINT ["/usr/local/bin/posthog-tool-runner"]
CMD ["--config", "/etc/posthog-tool-runner/config.yaml"]
