# Stage 1: Build the wheel
FROM python:3.12-slim AS builder
WORKDIR /build

COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --no-cache-dir build && python -m build --wheel

# Stage 2: Minimal runtime image
FROM python:3.12-slim

# Install the wheel built in stage 1
COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl

# AWS credentials are mounted at runtime — never baked into the image.
# Usage:
#   docker run --rm \
#     -v ~/.aws:/root/.aws:ro \
#     -v $(pwd):/workspace \
#     -w /workspace \
#     ghcr.io/samionex/infrakit deploy --config infrakit.yaml --auto-approve

ENTRYPOINT ["infrakit"]
CMD ["--help"]
