# OrcaSlicer HTTP API (upstream AFKFelix/orca-slicer-api) built from a pinned commit.
# AGPL-3.0: this service runs as a separate container; see README.md (license note).
#
# Deviations from upstream Dockerfile (needed to run at all):
#  - package.json is copied to /app (upstream "type":"module" is required, otherwise
#    the ESM output in dist/ is loaded as CommonJS and fails).
#  - CMD is "node dist/index.js" (upstream CMD "node app/dist/index.js" points to a
#    path that does not exist, because the build output is copied to /app/dist).

FROM node:22-bookworm AS build

ARG UPSTREAM_REPO=https://github.com/AFKFelix/orca-slicer-api.git
ARG UPSTREAM_REF=a9a28f0a7b0c6f51b9be158509e9e9677532b868
ARG ORCA_VERSION=2.4.2
ARG TARGETARCH

RUN apt-get update \
	&& apt-get install -y --no-install-recommends git ca-certificates curl \
	&& rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN git clone -q "$UPSTREAM_REPO" /app \
	&& git checkout -q "$UPSTREAM_REF" \
	&& test "$(git rev-parse HEAD)" = "$UPSTREAM_REF"

# Download OrcaSlicer (AMD64 official AppImage; ARM64 handled as upstream does)
RUN if [ "$TARGETARCH" = "arm64" ]; then \
	if dpkg --compare-versions "$ORCA_VERSION" ge "2.4.0"; then \
	URL="https://github.com/OrcaSlicer/OrcaSlicer/releases/download/v${ORCA_VERSION}/OrcaSlicer_Linux_AppImage_Ubuntu2404_aarch64_V${ORCA_VERSION}.AppImage"; \
	else \
	URL="https://github.com/kldzj/orca-slicer-arm64/releases/download/v${ORCA_VERSION}-arm64/OrcaSlicer-${ORCA_VERSION}-arm64-linux.AppImage"; \
	fi; \
	else \
	URL="https://github.com/OrcaSlicer/OrcaSlicer/releases/download/v${ORCA_VERSION}/OrcaSlicer_Linux_AppImage_Ubuntu2404_V${ORCA_VERSION}.AppImage"; \
	fi && \
	echo "Downloading $URL" && \
	curl -fo orca.AppImage -L "$URL" && \
	chmod +x orca.AppImage && \
	./orca.AppImage --appimage-extract && \
	rm orca.AppImage

RUN npm ci
RUN npm run build

FROM ubuntu:24.04

ARG UPSTREAM_REF=a9a28f0a7b0c6f51b9be158509e9e9677532b868
ARG ORCA_VERSION=2.4.2

RUN apt-get update \
	&& apt-get upgrade -y \
	&& apt-get install -y --no-install-recommends \
	curl ca-certificates gnupg \
	&& mkdir -p /etc/apt/keyrings \
	&& curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
	&& echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
	&& apt-get update \
	&& apt-get install -y --no-install-recommends \
	nodejs \
	libgl1 libgl1-mesa-dri libegl1 libopengl0 libglu1-mesa \
	libsm6 libice6 libmspack0t64 \
	libgtk-3-0 \
	libgstreamer1.0-0 libgstreamer-plugins-base1.0-0 \
	libwebkit2gtk-4.1-0 \
	&& update-ca-certificates \
	&& rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=build /app/package.json /app/package.json
COPY --from=build /app/dist/src /app/dist
COPY --from=build /app/node_modules /app/node_modules
COPY --from=build /app/squashfs-root /app/squashfs-root

ENV PORT=3000
ENV ORCASLICER_PATH=/app/squashfs-root/AppRun
ENV ORCASLICER_RESOURCES_PATH=/app/squashfs-root/resources
ENV ORCASLICER_VERSION=${ORCA_VERSION}
ENV SYSTEM_PROFILE_PATH=/app/system-profiles
ENV NODE_ENV=production
ENV UPSTREAM_REF=${UPSTREAM_REF}

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
	CMD curl -f http://localhost:3000/health || exit 1

CMD ["node", "dist/index.js"]
