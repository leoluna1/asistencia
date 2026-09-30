import { describe, expect, it } from 'vitest';
import { mensajeDeErrorDeBlob, primerMensajeDeError } from './errores';

describe('primerMensajeDeError', () => {
  it('lee el formato de ValidationError levantado a mano en la vista', () => {
    expect(primerMensajeDeError({ cedula: 'No existe.' })).toBe('No existe.');
  });

  it('lee el formato de validación de serializer (lista)', () => {
    expect(primerMensajeDeError({ correo: ['Ya está en uso.'] })).toBe('Ya está en uso.');
  });

  it('devuelve null si no hay nada legible', () => {
    expect(primerMensajeDeError(null)).toBeNull();
    expect(primerMensajeDeError('texto suelto')).toBeNull();
  });
});

describe('mensajeDeErrorDeBlob', () => {
  it('extrae el mensaje de un error que vino como Blob (descargas)', async () => {
    const blob = new Blob([JSON.stringify({ formato: 'El PDF está limitado a 2000 filas.' })], {
      type: 'application/json'
    });
    await expect(mensajeDeErrorDeBlob(blob)).resolves.toBe('El PDF está limitado a 2000 filas.');
  });

  it('no rompe si el Blob no es JSON', async () => {
    await expect(mensajeDeErrorDeBlob(new Blob(['<html>502</html>']))).resolves.toBeNull();
  });

  it('sigue funcionando con un error ya parseado', async () => {
    await expect(mensajeDeErrorDeBlob({ formato: 'Debe ser csv o pdf.' })).resolves.toBe(
      'Debe ser csv o pdf.'
    );
  });
});
