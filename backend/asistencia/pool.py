"""Pool de embeddings en memoria para la verificación 1:N.

Por qué existe (medido el 2026-09-28 con 20.005 postulantes sembrados, que es
el volumen real de la convocatoria): `VerificarAsistenciaView` traía TODOS los
embeddings desde Postgres en cada request — 20,5 MB y 875 ms — mientras que el
reconocimiento facial en sí (detección + anti-spoofing + embedding) son 11 ms.
O sea: el 93% del tiempo de cada verificación era mover datos que casi nunca
cambian, y con varios puestos verificando a la vez eso castiga a la base justo
el día de la prueba.

Acá se guarda una sola copia de la matriz (N x 128, ya normalizada por fila) en
el proceso, y se reconstruye solo cuando hace falta:

- al vencer `SEGUNDOS_FRESCURA` (cota de desactualización),
- cuando alguien llama `invalidar()` (registro nuevo, foto adicional nueva),
- y, como red de seguridad, cuando la verificación NO encuentra a nadie: ahí
  `VerificarAsistenciaView` recarga y reintenta, de modo que un postulante que
  acaba de registrarse en OTRO proceso/worker no quede sin poder verificarse.

Con varios workers (gunicorn) cada uno mantiene su propia copia: son ~20 MB por
worker, y la red de seguridad de arriba cubre la desactualización entre ellos.
"""
from __future__ import annotations

import threading
import time

import numpy as np

from .models import FotoPostulante, Postulante

# Cota máxima de desactualización del pool. 30s es holgado para este flujo: el
# registro pasa ANTES del día de la prueba (ver docs/00-REFERENCIA-PROYECTO.md),
# no mientras la fila de gente se verifica.
SEGUNDOS_FRESCURA = 30

_lock = threading.Lock()
_ids: np.ndarray | None = None
_matriz: np.ndarray | None = None
_cargado_en: float = 0.0


def obtener(forzar: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """Devuelve (ids, matriz normalizada) del pool, releyendo si hace falta.

    `forzar=True` relee siempre — lo usa el reintento tras no encontrar a nadie.
    """
    global _ids, _matriz, _cargado_en
    with _lock:
        vencido = (time.monotonic() - _cargado_en) > SEGUNDOS_FRESCURA
        if forzar or _matriz is None or vencido:
            _ids, _matriz = _leer_de_la_base()
            _cargado_en = time.monotonic()
        return _ids, _matriz


def invalidar() -> None:
    """Descarta el pool: la próxima verificación lo relee de la base."""
    global _ids, _matriz, _cargado_en
    with _lock:
        _ids, _matriz, _cargado_en = None, None, 0.0


def edad_segundos() -> float:
    """Hace cuánto se leyó el pool (infinito si no hay nada cargado)."""
    return float("inf") if _matriz is None else time.monotonic() - _cargado_en


def _leer_de_la_base() -> tuple[np.ndarray, np.ndarray]:
    # La foto principal de cada postulante + cada ángulo adicional
    # (FotoPostulante), aplanados: dos filas pueden apuntar al mismo postulante.
    filas = list(
        Postulante.objects.exclude(embedding__isnull=True).values_list("id", "embedding")
    ) + list(FotoPostulante.objects.values_list("postulante_id", "embedding"))

    if not filas:
        return np.empty(0, dtype=np.int64), np.empty((0, 128), dtype=np.float32)

    ids = np.fromiter((fila[0] for fila in filas), dtype=np.int64, count=len(filas))
    # float32: la mitad de memoria que float64 y sobra para una similitud coseno
    # que se compara contra un umbral de 3 decimales (0.363).
    matriz = np.array([fila[1] for fila in filas], dtype=np.float32)
    normas = np.linalg.norm(matriz, axis=1, keepdims=True)
    normas[normas == 0] = 1.0  # un embedding nulo no debe dar NaN
    return ids, matriz / normas


def mejor_coincidencia_en_pool(
    embedding_consulta, ids: np.ndarray, matriz: np.ndarray
) -> tuple[int, float] | None:
    """1:N contra la matriz ya normalizada. Mismo resultado que
    `facial.mejor_coincidencia`, sin rearmar la matriz en cada request.

    Devuelve (id, similitud_coseno) del más parecido, o None si el pool está
    vacío. No aplica el umbral — eso lo decide el llamador.
    """
    if len(ids) == 0:
        return None

    consulta = np.asarray(embedding_consulta, dtype=np.float32)
    norma = np.linalg.norm(consulta)
    if norma == 0:
        return None

    similitudes = matriz @ (consulta / norma)
    mejor = int(np.argmax(similitudes))
    return int(ids[mejor]), float(similitudes[mejor])
