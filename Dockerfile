# Upstream image: derhuerst/build123d :with_yacv tag.
# Includes both build123d and yacv-server. Multi-arch index digest pinned.
# Upstream only publishes linux/amd64; on aarch64 hosts (Snapdragon WSL,
# Apple Silicon, etc.) the image runs under qemu emulation. Slower but works.
# To refresh: docker buildx imagetools inspect ghcr.io/derhuerst/build123d:with_yacv
FROM --platform=linux/amd64 ghcr.io/derhuerst/build123d@sha256:998bda94e010602ee1a4c08db76174ea9b2e59732b7eda54a96238518be6fa85

USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends sqlite3 gcc libc6-dev libsqlite3-dev \
 && rm -rf /var/lib/apt/lists/*

# Compile ltree.so for the container's arch (amd64 under qemu) — the host's
# vendored aarch64 .so is not loadable here.
COPY vendor/ltree_sqlite.c /tmp/ltree_sqlite.c
RUN gcc -Wall -O2 -fPIC -shared -o /usr/local/lib/ltree.so /tmp/ltree_sqlite.c \
 && rm /tmp/ltree_sqlite.c

COPY pyproject.toml /tmp/build/
COPY src/    /tmp/build/src/
COPY vendor/ /tmp/build/vendor/
RUN pip install --no-cache-dir /tmp/build && rm -rf /tmp/build

USER 1000
WORKDIR /project
# ezdxf scans $HOME/.cache on import for a cache directory. UID 1000 can't
# write to / (the default $HOME when unset), so ezdxf prints a warning on
# every mk run. /tmp is world-writable inside the container.
ENV HOME=/tmp
ENTRYPOINT ["mk"]
