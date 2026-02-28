FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml readme.md ./
COPY src ./src
COPY examples ./examples

RUN python -m pip install --upgrade pip && \
    python -m pip install .

ENTRYPOINT ["agent-eval"]
CMD ["--help"]
