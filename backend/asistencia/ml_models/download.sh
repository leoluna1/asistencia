#!/bin/sh
# Descarga los modelos de reconocimiento facial y anti-spoofing (todos Apache 2.0).
# No se comitean al repo por su tamaño (~40MB) — correr este script una vez
# después de clonar o antes de levantar el backend.
set -e
cd "$(dirname "$0")"

curl -sL -o face_detection_yunet_2023mar.onnx \
  https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx

curl -sL -o face_recognition_sface_2021dec.onnx \
  https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx

# Anti-spoofing (detección de vida): exportación a ONNX de MiniFASNetV2, del propio
# Silent-Face-Anti-Spoofing de MiniVision (ver docs/00-REFERENCIA-PROYECTO.md).
curl -sL -o MiniFASNetV2.onnx \
  https://github.com/yakhyo/face-anti-spoofing/releases/download/weights/MiniFASNetV2.onnx

echo "Listo:"
ls -la *.onnx
