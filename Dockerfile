# Hugging Face Spaces (Docker SDK). Runs the Flask app on port 7860.
FROM python:3.11-slim

# WeasyPrint needs Pango/Cairo/GDK-Pixbuf; fonts-noto-cjk for Japanese glyphs.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangocairo-1.0-0 libpangoft2-1.0-0 \
        libgdk-pixbuf-2.0-0 libcairo2 libffi-dev shared-mime-info \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only torch first so the multi-GB CUDA stack is not pulled.
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Spaces run the container as a non-root user; keep all caches/temp under writable /tmp.
ENV PORT=7860 \
    HF_HOME=/tmp/hf \
    HUGGINGFACE_HUB_CACHE=/tmp/hf \
    TRANSFORMERS_CACHE=/tmp/hf \
    MPLCONFIGDIR=/tmp/mpl

EXPOSE 7860
CMD ["python", "app.py"]
