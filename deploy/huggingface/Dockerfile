FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    EVOMIND_PUBLIC=1 \
    EVOMIND_MAX_REPO_MB=400

WORKDIR /home/user/app
COPY --chown=user backend/requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt
COPY --chown=user backend/ .

EXPOSE 7860
CMD ["uvicorn", "evomind.api.main:app", "--host", "0.0.0.0", "--port", "7860"]
