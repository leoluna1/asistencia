FROM python:3.12-slim

# Libs nativas para weasyprint (equivalente Linux de brew install cairo pango
# gdk-pixbuf, ya documentado en requirements.txt) + libGL/libglib para
# opencv-python (trae dependencias de GUI que una imagen slim no tiene).
# curl: download.sh, si el build parte de un clon sin los modelos .onnx.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# Los .onnx están en .gitignore: en un clon nuevo no existen. download.sh
# verifica el sha256 de cada modelo antes de dejarlo en la imagen.
RUN [ -f asistencia/ml_models/MiniFASNetV2.onnx ] || sh asistencia/ml_models/download.sh
RUN chmod +x docker-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
