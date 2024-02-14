FROM mcr.microsoft.com/devcontainers/base:jammy

RUN --mount=target=/var/lib/apt/lists,type=cache,sharing=locked \
    --mount=target=/var/cache/apt,type=cache,sharing=locked \
    apt update \
 && apt install --assume-yes bash-completion
 