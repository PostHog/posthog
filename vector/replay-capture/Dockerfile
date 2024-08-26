FROM alpine as config-builder

RUN apk add -U yq

WORKDIR /config
COPY vector.yaml .
# evaluate with yq, basically to expand anchors (which vector doesn't support)
RUN yq -i e 'explode(.)' vector.yaml

# fork of vector from this branch: https://github.com/frankh/vector/tree/main
# includes 2 fixed: 1 to make Kafka temporary errors return 500 not 400
# and 1 to allow us to set response body on the http source
FROM frankh/vector:0.41.0-patched

COPY --from=config-builder /config/vector.yaml /etc/vector/vector.yaml
