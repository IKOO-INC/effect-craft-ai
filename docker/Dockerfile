# Image Docker berisi `effectcraft-cli` — dipakai mode koneksi "Docker".
#
# Catatan penting:
#  * Repository storytold/effectcraft TIDAK menyertakan Dockerfile, dan kami tidak dapat memverifikasi
#    keberadaan image publik `ghcr.io/storytold/effectcraft` (ghcr.io tidak bisa diakses dari lingkungan
#    pengembangan). Karena itu nama image bisa diubah di Settings, dan image di bawah bisa Anda bangun sendiri.
#  * `effectcraft-cli` bergantung pada `effectcraft-ui-egui` dan `effectcraft-gpu` (wgpu). Build perlu
#    header X11/wayland/vulkan, dan render di container tanpa GPU memakai rasteriser perangkat lunak
#    (Mesa llvmpipe/lavapipe) — lebih lambat, tetapi tidak butuh GPU.
#
#   docker build -t effectcraft-cli:0.24.1 docker/
#   docker run --rm -v "$PWD/projects:/work" effectcraft-cli:0.24.1 --help
#
# Aplikasi memanggil: docker run --rm -v <folder-proyek>:/work <image> <command> …
# sehingga image harus punya ENTRYPOINT `effectcraft-cli` dan working dir /work.

# ---------------------------------------------------------------- tahap build
FROM rust:1.82-bookworm AS build

ARG EFFECTCRAFT_REF=v0.24.1
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       git pkg-config cmake libssl-dev \
       libx11-dev libxkbcommon-dev libwayland-dev libgl1-mesa-dev libvulkan-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN git clone --depth 1 --branch "${EFFECTCRAFT_REF}" https://github.com/storytold/effectcraft.git .

# Hanya CLI (tanpa aplikasi GUI), sesuai kebutuhan aplikasi ini.
RUN cargo build --release -p effectcraft-cli

# --------------------------------------------------------------- tahap runtime
FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates libssl3 libfontconfig1 fonts-dejavu-core fonts-liberation \
       libgl1 libegl1 libvulkan1 mesa-vulkan-drivers libgl1-mesa-dri \
       libx11-6 libxkbcommon0 libwayland-client0 \
    && rm -rf /var/lib/apt/lists/*

# Tanpa GPU: paksa wgpu memakai OpenGL/Mesa (llvmpipe). Bisa ditimpa saat `docker run -e`.
ENV WGPU_BACKEND=gl \
    LIBGL_ALWAYS_SOFTWARE=1 \
    EFFECTCRAFT_HEADLESS=1

COPY --from=build /src/target/release/effectcraft-cli /usr/local/bin/effectcraft-cli

RUN mkdir -p /work
WORKDIR /work

ENTRYPOINT ["effectcraft-cli"]
CMD ["--help"]
