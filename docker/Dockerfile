# Image Docker berisi `effectcraft-cli` — dipakai mode koneksi "Docker".
#
# Catatan penting: repository storytold/effectcraft TIDAK menyertakan Dockerfile dan kami tidak
# dapat memverifikasi keberadaan image publik `ghcr.io/storytold/effectcraft` (registry ghcr.io
# tidak bisa diakses dari lingkungan pengembangan ini). Karena itu aplikasi memakai nama image
# yang bisa diubah di Settings, dan image di bawah ini bisa Anda bangun sendiri:
#
#   docker build -t effectcraft-cli:0.24.1 docker/
#   docker run --rm -v "$PWD/projects:/work" effectcraft-cli:0.24.1 --help
#
# Aplikasi menjalankan: docker run --rm -v <folder-proyek>:/work <image> <command> …
# sehingga image harus punya ENTRYPOINT `effectcraft-cli` dan working dir /work.

# ---------------------------------------------------------------- tahap build
FROM rust:1.82-bookworm AS build

ARG EFFECTCRAFT_REF=v0.24.1
RUN apt-get update \
    && apt-get install -y --no-install-recommends git pkg-config libssl-dev cmake \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN git clone --depth 1 --branch "${EFFECTCRAFT_REF}" https://github.com/storytold/effectcraft.git .

# Hanya CLI + crate yang dibutuhkannya (tanpa aplikasi GUI/egui).
RUN cargo build --release -p effectcraft-cli

# --------------------------------------------------------------- tahap runtime
FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libssl3 libfontconfig1 \
       fonts-dejavu-core fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /src/target/release/effectcraft-cli /usr/local/bin/effectcraft-cli

RUN mkdir -p /work
WORKDIR /work

# CLI EffectCraft butuh berkas proyek (.ecproj) dan menulis hasil render ke folder /work.
ENTRYPOINT ["effectcraft-cli"]
CMD ["--help"]
