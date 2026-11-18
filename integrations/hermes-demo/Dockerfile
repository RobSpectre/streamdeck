FROM ubuntu:24.04 AS blank
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ca-certificates curl git build-essential python3 python3-venv python3-pip \
    libffi-dev libssl-dev libatomic1 pkg-config procps ripgrep xz-utils unzip less \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /bin/bash demo
ARG HERMES_REVISION=7ce190446e548e2e1c0ae6ba0225be0490d12fc2
RUN curl -fsSL "https://raw.githubusercontent.com/NousResearch/hermes-agent/${HERMES_REVISION}/scripts/install.sh" \
    -o /opt/hermes-install.sh
COPY install-hermes /usr/local/bin/install-hermes
COPY demo.bashrc /opt/demo.bashrc
RUN chmod 755 /usr/local/bin/install-hermes && \
    printf '%s\n' "$HERMES_REVISION" > /opt/hermes-revision
USER demo
ENV HOME=/home/demo
ENV PATH=/home/demo/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
WORKDIR /home/demo
CMD ["/bin/bash", "--rcfile", "/opt/demo.bashrc", "-i"]

FROM blank AS ready
RUN install-hermes --skip-setup --skip-browser --skip-computer-use --non-interactive
