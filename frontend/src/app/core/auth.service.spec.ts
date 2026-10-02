import { TestBed } from '@angular/core/testing';
import { asegurarLocalStorage } from './testing-storage';

asegurarLocalStorage();
import { provideHttpClient } from '@angular/common/http';
import { AuthService } from './auth.service';

function token(claims: object): string {
  return `x.${btoa(JSON.stringify(claims))}.y`;
}
const enSegundos = (delta: number) => Math.floor(Date.now() / 1000) + delta;

describe('AuthService', () => {
  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({ providers: [provideHttpClient()] });
  });

  it('descarta un token vencido al arrancar', () => {
    localStorage.setItem('asistencia_access_token', token({ exp: enSegundos(-60), is_staff: true }));
    const auth = TestBed.inject(AuthService);
    expect(auth.isAuthenticated()).toBe(false);
    expect(auth.isStaff()).toBe(false);
    expect(localStorage.getItem('asistencia_access_token')).toBeNull();
  });

  it('acepta un token vigente de agente', () => {
    localStorage.setItem('asistencia_access_token', token({ exp: enSegundos(3600), is_staff: true }));
    const auth = TestBed.inject(AuthService);
    expect(auth.isAuthenticated()).toBe(true);
    expect(auth.isStaff()).toBe(true);
  });

  it('cierra la sesión si el token vence mientras la app está abierta', () => {
    localStorage.setItem('asistencia_access_token', token({ exp: enSegundos(3600), is_staff: true }));
    const auth = TestBed.inject(AuthService);
    localStorage.setItem('asistencia_access_token', token({ exp: enSegundos(-1), is_staff: true }));
    auth.cerrarSiVencida();
    expect(auth.isStaff()).toBe(false);
  });
});
