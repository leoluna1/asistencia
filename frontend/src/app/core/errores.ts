// DRF a veces manda {"campo": "mensaje"} (ValidationError levantado a mano en la vista)
// y a veces {"campo": ["mensaje"]} (validación de serializer) — normaliza ambos casos.
export function primerMensajeDeError(error: unknown): string | null {
  if (!error || typeof error !== 'object') return null;
  const valor = Object.values(error as Record<string, unknown>)[0];
  if (Array.isArray(valor)) return valor[0] ?? null;
  return typeof valor === 'string' ? valor : null;
}

/** Las descargas se piden con `responseType: 'blob'`, así que un error del
 * backend también llega como Blob en vez de JSON ya parseado — hay que leerlo
 * para poder mostrar el mensaje real (ej. el límite de filas del PDF) en vez
 * de un "no se pudo" genérico que no le dice al agente qué hacer. */
export async function mensajeDeErrorDeBlob(error: unknown): Promise<string | null> {
  if (!(error instanceof Blob)) return primerMensajeDeError(error);
  try {
    return primerMensajeDeError(JSON.parse(await error.text()));
  } catch {
    return null;
  }
}
