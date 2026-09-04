#!/bin/sh
# Descarga los modelos de reconocimiento facial (Apache 2.0, opencv/opencv_zoo).
# No se comitean al repo por su tamaño (~37MB) — correr este script una vez
# después de clonar o antes de levantar el backend.
set -e
cd "$(dirname "$0")"

curl -sL -o face_detection_yunet_2023mar.onnx \
  https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx

curl -sL -o face_recognition_sface_2021dec.onnx \
  https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx

echo "Listo:"
ls -la *.onnx
