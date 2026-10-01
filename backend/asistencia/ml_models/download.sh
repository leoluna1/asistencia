#!/bin/sh
# Descarga los modelos de reconocimiento facial y anti-spoofing (todos Apache 2.0).
# No se comitean al repo por su tamaño (~40MB) — correr este script una vez
# después de clonar o antes de levantar el backend.
set -e
cd "$(dirname "$0")"

curl -fsSL -o face_detection_yunet_2023mar.onnx \
  https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx

curl -fsSL -o face_recognition_sface_2021dec.onnx \
  https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx

# Anti-spoofing (detección de vida): exportación a ONNX de MiniFASNetV2, del propio
# Silent-Face-Anti-Spoofing de MiniVision (ver docs/00-REFERENCIA-PROYECTO.md).
curl -fsSL -o MiniFASNetV2.onnx \
  https://github.com/yakhyo/face-anti-spoofing/releases/download/weights/MiniFASNetV2.onnx

# Los URLs apuntan a referencias mutables (rama main, release "weights" de un
# tercero): sin verificar el hash, un modelo cambiado upstream (ej. un
# anti-spoofing que siempre dice "real") entraba a producción sin aviso.
# Hashes de las copias en uso desde 2026-09-06. Si upstream cambia a propósito,
# revisar el modelo nuevo y actualizar acá.
cat > SHA256SUMS <<'SUMS'
8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4  face_detection_yunet_2023mar.onnx
0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79  face_recognition_sface_2021dec.onnx
b32929adc2d9c34b9486f8c4c7bc97c1b69bc0ea9befefc380e4faae4e463907  MiniFASNetV2.onnx
SUMS
if command -v sha256sum >/dev/null 2>&1; then sha256sum -c SHA256SUMS; else shasum -a 256 -c SHA256SUMS; fi
rm SHA256SUMS

echo "Listo:"
ls -la *.onnx
