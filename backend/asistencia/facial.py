"""Detección y embedding facial con OpenCV (YuNet + SFace, ambos Apache 2.0).

Sin TensorFlow ni InsightFace: los modelos .onnx corren directo sobre cv2.dnn.
Ver docs/00-REFERENCIA-PROYECTO.md para el porqué de esta elección.
"""
from pathlib import Path

import cv2
import numpy as np

MODELS_DIR = Path(__file__).resolve().parent / "ml_models"

_detector = None
_recognizer = None


class RostroNoDetectado(Exception):
    """La foto no tiene un rostro detectable."""


def _get_detector():
    global _detector
    if _detector is None:
        _detector = cv2.FaceDetectorYN_create(
            str(MODELS_DIR / "face_detection_yunet_2023mar.onnx"), "", (320, 320)
        )
    return _detector


def _get_recognizer():
    global _recognizer
    if _recognizer is None:
        _recognizer = cv2.FaceRecognizerSF_create(
            str(MODELS_DIR / "face_recognition_sface_2021dec.onnx"), ""
        )
    return _recognizer


def get_embedding(image_bgr: np.ndarray) -> list[float]:
    """Detecta el rostro más confiable de la imagen y devuelve su embedding (128 floats).

    Lanza RostroNoDetectado si no encuentra ningún rostro.
    """
    detector = _get_detector()

    # ponytail: YuNet falla en fotos a resolución completa de celular (>4MP) — redimensionar
    # al lado máximo de 640px lo arregla sin perder precisión útil para este caso de uso.
    h, w = image_bgr.shape[:2]
    escala = 640 / max(h, w)
    if escala < 1:
        image_bgr = cv2.resize(image_bgr, (int(w * escala), int(h * escala)))
        h, w = image_bgr.shape[:2]

    detector.setInputSize((w, h))
    _, faces = detector.detect(image_bgr)
    if faces is None or len(faces) == 0:
        raise RostroNoDetectado("No se detectó ningún rostro en la foto")

    # faces: filas [x, y, w, h, 5 landmarks..., score] — nos quedamos con el de mayor score.
    mejor_rostro = faces[np.argmax(faces[:, -1])]

    recognizer = _get_recognizer()
    alineado = recognizer.alignCrop(image_bgr, mejor_rostro)
    embedding = recognizer.feature(alineado)
    return embedding.flatten().tolist()
