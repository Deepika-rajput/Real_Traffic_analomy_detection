# Backend image: FastAPI + camera workers + your trained model (CPU only).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app

# CPU-only PyTorch (much smaller than the default CUDA build)
RUN pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

# opencv-python-headless: same API as opencv-python, no GUI libraries needed in a container
# imageio-ffmpeg: bundles an ffmpeg binary, used to make browser-playable H.264 clips
RUN pip install fastapi "uvicorn[standard]" python-multipart imageio-ffmpeg \
    opencv-python-headless numpy httpx

# The code is also copied in so the image works on its own; docker-compose bind-mounts the project
# folder over /app so edits, videos/, temporal.pth and features/ are shared with your machine.
COPY . /app

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
