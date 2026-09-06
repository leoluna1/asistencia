// DRF a veces manda {"campo": "mensaje"} (ValidationError levantado a mano en la vista)
// y a veces {"campo": ["mensaje"]} (validación de serializer) — normaliza ambos casos.
export function primerMensajeDeError(error: unknown): string | null {
  if (!error || typeof error !== 'object') return null;
  const valor = Object.values(error as Record<string, unknown>)[0];
  if (Array.isArray(valor)) return valor[0] ?? null;
  return typeof valor === 'string' ? valor : null;
}
