FROM golang:1.27.1-bookworm@sha256:648f440f42a0958804efb24df176f806f9d353b41f1c0627f666428e40310f6b AS build

WORKDIR /src

COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download

COPY . ./

ARG COMMIT_HASH=unknown
ARG TARGETOS=linux
ARG TARGETARCH
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=${TARGETOS} GOARCH=${TARGETARCH} go build \
    -trimpath \
    -ldflags="-s -w" \
    -o /out/hogql-language-service \
    ./cmd/server && \
    printf '%s' "${COMMIT_HASH}" > /out/commit.txt

FROM scratch

WORKDIR /app

COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=build --chown=65532:65532 /out/hogql-language-service /app/hogql-language-service
COPY --from=build --chown=65532:65532 /out/commit.txt /app/commit.txt

ENV LISTEN_ADDR=0.0.0.0:8091

EXPOSE 8091

USER 65532:65532

ENTRYPOINT ["/app/hogql-language-service"]
