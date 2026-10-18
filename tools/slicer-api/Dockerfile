FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1 \
	PIP_NO_CACHE_DIR=1 \
	PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app ./app
COPY profiles ./profiles

# Non-root runtime user; /data holds job records and outputs (volume).
RUN useradd --uid 10001 --create-home app \
	&& mkdir -p /data \
	&& chown app:app /data
USER app

ENV DATA_DIR=/data \
	ORCA_URL=http://orca:3000 \
	MAX_CONCURRENT_JOBS=1 \
	JOB_RETENTION_HOURS=24

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
	CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4).status == 200 else 1)"

# One worker only: the job queue and worker tasks live in this process.
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
