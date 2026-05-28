FROM node:24-alpine

# Run as a non-root user inside the container — the sandbox is no-network,
# but we still want a defense-in-depth posture if a tool tries to touch the
# filesystem outside /workdir.
RUN addgroup -S sandbox && adduser -S -G sandbox sandbox

# Copy the in-container host. No dependencies — both files are pure Node
# stdlib so we can stay on a thin image.
COPY src/host.js /sandbox/host.js
COPY src/dispatch.js /sandbox/dispatch.js
RUN chmod +x /sandbox/host.js /sandbox/dispatch.js

# /workdir is bind-mounted by the runner-side DockerSandbox at
# `docker run -v <workdir>:/workdir`. The host writes /workdir/host.alive
# on boot; the dispatcher reads /workdir/{request,response}.json per exec.
RUN mkdir -p /workdir && chown sandbox:sandbox /workdir
USER sandbox
WORKDIR /workdir

# Default to running the host — `docker run <image>` keeps the container
# alive; the runner then issues `docker exec ... dispatch.js ...` per call.
CMD ["node", "/sandbox/host.js"]
