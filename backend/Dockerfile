# Serving image. Python 3.12 rather than the training stack's 3.14: the models ship as frozen
# ONNX graphs, so the container needs neither scikit-learn nor torch, and pinning to a bleeding
# edge interpreter buys nothing while risking wheels that do not exist yet.
FROM python:3.12-slim-bookworm

# Determinism. Set before any Python starts, because ONNX Runtime reads these when it builds a
# session and a byte-identical-output requirement that depends on import order is not one.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1

WORKDIR /srv

RUN groupadd --system myolens && useradd --system --gid myolens --home /srv myolens

COPY requirements.txt .
# `--require-hashes` is a store_true flag, not a key=value option. Writing it as
# `--require-hashes=false` makes pip print its usage banner and exit non-zero, which is what
# failed the first Cloud Run deploy: the four test jobs were green, the image simply never built.
# It is left recorded here because it is the exact class of defect a test suite cannot catch --
# nothing in the repository executes the Dockerfile until the pipeline does.
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY artifacts ./artifacts

USER myolens

# Cloud Run supplies PORT. One worker: the container is sized at 2 GiB and a ten-minute CSV
# parsed by pandas transiently needs several times the file size, so concurrent parses inside
# one instance would OOM. Concurrency comes from instances, not from workers.
ENV PORT=8080
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1
