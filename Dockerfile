FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-server \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/sshd /var/lib/bashgame/players

COPY sshd_config /etc/ssh/sshd_config
COPY bashgame_shell.py /usr/local/bin/bashgame-shell
COPY game_state.py /usr/local/bin/game_state.py
COPY bashgame_dashboard.py /usr/local/bin/bashgame_dashboard.py
COPY bashgame-entrypoint /usr/local/sbin/bashgame-entrypoint

RUN chmod 0755 /usr/local/bin/bashgame-shell /usr/local/bin/bashgame_dashboard.py /usr/local/sbin/bashgame-entrypoint

EXPOSE 22 8080
ENTRYPOINT ["/usr/local/sbin/bashgame-entrypoint"]
