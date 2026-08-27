FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Roda como o mesmo uid/gid do host (bind mount): evita que job_hunter.db e
# outros arquivos gerados em runtime fiquem donos de root no diretório do host.
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd -g "${APP_GID}" appuser && \
    useradd -u "${APP_UID}" -g "${APP_GID}" -M appuser
USER appuser

CMD ["python", "run_all.py"]
