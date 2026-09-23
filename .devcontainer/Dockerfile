ARG PYTHON_VERSION=3.12

FROM ubuntu:24.04

ARG PYTHON_VERSION

ENV DEBIAN_FRONTEND=noninteractive

# Install base dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    gnupg \
    ca-certificates \
    software-properties-common \
    git \
    tmux \
    && rm -rf /var/lib/apt/lists/*

# Install Python
RUN add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        python${PYTHON_VERSION} \
        python${PYTHON_VERSION}-venv \
        python${PYTHON_VERSION}-dev \
        python3-pip \
    && update-alternatives --install /usr/bin/python python /usr/bin/python${PYTHON_VERSION} 1 \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python${PYTHON_VERSION} 1 \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js (LTS) — required by the Claude Code CLI
RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user with UID 1000 to match typical host user UID.
# Ubuntu 24.04 base image ships with an "ubuntu" user at UID 1000; remove it first.
RUN userdel -r ubuntu 2>/dev/null || true \
    && useradd -m -u 1000 -s /bin/bash vscode
USER vscode
WORKDIR /home/vscode
RUN mkdir -p /home/vscode/.config

# Install Claude Code CLI as the vscode user so it can write its own caches and state.
ENV NPM_CONFIG_PREFIX=/home/vscode/.npm-global
ENV PATH=/home/vscode/.npm-global/bin:${PATH}
RUN npm install -g @anthropic-ai/claude-code

# Install Hatch (project task runner) into its own venv, pipx-style — Ubuntu 24.04's
# system pip is externally managed (PEP 668), so a user-level pip install is refused.
ENV PATH=/home/vscode/.local/bin:${PATH}
RUN python3 -m venv /home/vscode/.local/share/hatch-venv \
    && /home/vscode/.local/share/hatch-venv/bin/pip install --no-cache-dir hatch \
    && mkdir -p /home/vscode/.local/bin \
    && ln -s /home/vscode/.local/share/hatch-venv/bin/hatch /home/vscode/.local/bin/hatch
