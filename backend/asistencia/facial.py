"""Detección, embedding y anti-spoofing facial con OpenCV (YuNet + SFace +
MiniFASNetV2, todos Apache 2.0).

Sin TensorFlow ni InsightFace ni onnxruntime: los modelos .onnx corren directo
sobre cv2.dnn. Ver docs/00-REFERENCIA-PROYECTO.md para el porqué de esta elección.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

MODELS_DIR = Path(__file__).resolve().parent / "ml_models"

# Umbral oficial de opencv_zoo/models/face_recognition_sface/sface.py (_threshold_cosine).
# Por debajo de esto, SFace lo considera una persona distinta.
UMBRAL_COINCIDENCIA = 0.363

# Recorte y tamaño de entrada esperados por MiniFASNetV2 (ver anti_spoof_predict.py del
# repo original minivision-ai/Silent-Face-Anti-Spoofing).
ESCALA_ANTISPOOFING = 2.7
TAMANO_ANTISPOOFING = (80, 80)

# Umbrales de calidad para la foto DE REGISTRO (la de referencia, más estricta que
# verificación). Ajustados a ojo — recalibrar con fotos reales si rechaza de más/menos.
UMBRAL_SCORE_REGISTRO = 0.9
PROPORCION_MIN_ROSTRO = 0.20  # ancho del rostro / ancho de la imagen
MARGEN_CENTRADO = 0.20  # desvío máx. del centro, como fracción del ancho/alto
TOLERANCIA_ROLL = 0.35  # |dif. y de ojos| / distancia interocular, cabeza inclinada
RANGO_YAW = (0.32, 0.68)  # posición relativa de la nariz entre los ojos, cara girada

_detector = None
_recognizer = None
_antispoofing = None


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


def _get_antispoofing():
    global _antispoofing
    if _antispoofing is None:
        _antispoofing = cv2.dnn.readNetFromONNX(str(MODELS_DIR / "MiniFASNetV2.onnx"))
    return _antispoofing


def detectar_rostro(image_bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Detecta el rostro más confiable de la imagen.

    Devuelve (imagen, rostro): la imagen puede venir redimensionada respecto a la
    original, y rostro es la fila cruda de YuNet [x, y, w, h, 5 landmarks..., score]
    en las coordenadas de esa imagen — ambos hacen falta para el resto del pipeline
    (embedding y anti-spoofing), por eso se devuelven juntos.

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
    return image_bgr, mejor_rostro


def calcular_embedding(image_bgr: np.ndarray, rostro: np.ndarray) -> list[float]:
    """Embedding (128 floats) del rostro ya detectado por detectar_rostro."""
    recognizer = _get_recognizer()
    alineado = recognizer.alignCrop(image_bgr, rostro)
    embedding = recognizer.feature(alineado)
    return embedding.flatten().tolist()


def get_embedding(image_bgr: np.ndarray) -> list[float]:
    """Atajo de detectar_rostro + calcular_embedding para cuando no hace falta
    anti-spoofing (registro: la foto la sube el propio postulante para sí mismo,
    no hay a quién suplantar todavía)."""
    image_bgr, rostro = detectar_rostro(image_bgr)
    return calcular_embedding(image_bgr, rostro)


def validar_calidad_registro(image_bgr: np.ndarray, rostro: np.ndarray) -> str | None:
    """Chequeos de encuadre para la foto DE REGISTRO (no para verificación: ahí ya
    alcanza con detectar+comparar). Sin esto, una foto de perfil, lejana o mal
    centrada queda como referencia y arruina el matching de ahí en adelante.

    No detecta lentes, gorra, bufanda ni cabello sobre la cara — YuNet solo da 5
    landmarks (ojos, nariz, boca), no hay forma confiable de ver eso con lo que ya
    corre en el pipeline. Eso se pide por texto en la UI y lo valida el agente que
    supervisa el registro, no el servidor (agregar un clasificador de atributos
    faciales para esto es una dependencia nueva completa, no una línea de más).

    Devuelve el primer problema encontrado (mensaje para mostrarle al postulante),
    o None si la foto pasa.
    """
    h, w = image_bgr.shape[:2]
    x, y, box_w, box_h = rostro[0:4]
    ojo1_x, ojo1_y, ojo2_x, ojo2_y = rostro[4:8]
    nariz_x, _nariz_y = rostro[8:10]
    score = rostro[14]

    if score < UMBRAL_SCORE_REGISTRO:
        return "La foto no es suficientemente nítida. Repite con buena luz, de frente a la cámara."

    if box_w < PROPORCION_MIN_ROSTRO * w:
        return "Acércate más a la cámara."

    centro_x, centro_y = x + box_w / 2, y + box_h / 2
    if abs(centro_x - w / 2) > MARGEN_CENTRADO * w or abs(centro_y - h / 2) > MARGEN_CENTRADO * h:
        return "Céntrate dentro del recuadro de la cámara."

    dist_interocular = abs(ojo2_x - ojo1_x) or 1.0
    if abs(ojo2_y - ojo1_y) / dist_interocular > TOLERANCIA_ROLL:
        return "Mantén la cabeza derecha, no la inclines."

    x_min, x_max = min(ojo1_x, ojo2_x), max(ojo1_x, ojo2_x)
    posicion_nariz = (nariz_x - x_min) / ((x_max - x_min) or 1.0)
    if not RANGO_YAW[0] <= posicion_nariz <= RANGO_YAW[1]:
        return "Mira directo a la cámara, no gires el rostro."

    return None


def _recortar_para_antispoofing(image_bgr: np.ndarray, rostro: np.ndarray) -> np.ndarray:
    src_h, src_w = image_bgr.shape[:2]
    x, y, box_w, box_h = (int(v) for v in rostro[:4])

    escala = min((src_h - 1) / box_h, (src_w - 1) / box_w, ESCALA_ANTISPOOFING)
    nuevo_w, nuevo_h = box_w * escala, box_h * escala
    cx, cy = x + box_w / 2, y + box_h / 2

    x1 = max(0, int(cx - nuevo_w / 2))
    y1 = max(0, int(cy - nuevo_h / 2))
    x2 = min(src_w - 1, int(cx + nuevo_w / 2))
    y2 = min(src_h - 1, int(cy + nuevo_h / 2))

    recorte = image_bgr[y1 : y2 + 1, x1 : x2 + 1]
    return cv2.resize(recorte, TAMANO_ANTISPOOFING)


def es_rostro_real(image_bgr: np.ndarray, rostro: np.ndarray) -> tuple[bool, float]:
    """Anti-spoofing: distingue un rostro real de una foto/pantalla mostrada a la
    cámara (riesgo señalado en docs/00-REFERENCIA-PROYECTO.md: alguien podría marcar
    la asistencia de otra persona con una foto suya). image_bgr y rostro deben venir
    de detectar_rostro (misma imagen ya redimensionada que usó el detector).

    Devuelve (es_real, confianza) — confianza es la probabilidad softmax de la clase
    ganadora (real o spoof), no solo de "real".
    """
    recorte = _recortar_para_antispoofing(image_bgr, rostro)

    # Sin swapRB ni normalización manual: el modelo espera BGR crudo en 0-255 porque
    # esta exportación a ONNX ya incluye la normalización dentro del propio grafo —
    # verificado contra las imágenes de muestra reales/falsas del repo original
    # (dividir por 255 acá encima rompe la predicción).
    blob = recorte.astype(np.float32).transpose(2, 0, 1)[np.newaxis, ...]

    red = _get_antispoofing()
    red.setInput(blob)
    salida = red.forward()[0]

    probs = np.exp(salida - np.max(salida))
    probs /= probs.sum()
    clase = int(np.argmax(probs))
    return clase == 1, float(probs[clase])


def mejor_coincidencia(
    embedding_consulta: list[float], candidatos: list[tuple[int, list[float]]]
) -> tuple[int, float] | None:
    """1:N — compara un embedding contra todos los candidatos (id, embedding).

    Devuelve (id, similitud_coseno) del más parecido, o None si no hay candidatos.
    No aplica el umbral — el llamador decide qué hacer con la similitud devuelta.
    """
    if not candidatos:
        return None

    ids, embeddings = zip(*candidatos)
    matriz = np.array(embeddings)
    consulta = np.array(embedding_consulta)

    similitudes = (matriz @ consulta) / (
        np.linalg.norm(matriz, axis=1) * np.linalg.norm(consulta)
    )
    mejor = int(np.argmax(similitudes))
    return ids[mejor], float(similitudes[mejor])
