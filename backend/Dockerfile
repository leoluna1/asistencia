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
RUN cd asistencia/ml_models && \
    { [ -f face_detection_yunet_2023mar.onnx ] && [ -f face_recognition_sface_2021dec.onnx ] \
      && [ -f MiniFASNetV2.onnx ]; } || sh download.sh
RUN chmod +x docker-entrypoint.sh

# Sin root: los endpoints públicos le pasan imágenes no confiables a Pillow y
# OpenCV; un bug en esos decoders no debería dar root en el contenedor.
# media/ y staticfiles/ creados con dueño app: un volumen nombrado nuevo hereda
# el dueño del directorio de la imagen.
RUN useradd -r -u 10001 app && mkdir -p /app/media /app/staticfiles && chown -R app /app
USER app

EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
