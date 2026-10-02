import { Injectable, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { API_BASE_URL } from './api-base';

const ACCESS_KEY = 'asistencia_access_token';
const REFRESH_KEY = 'asistencia_refresh_token';
const USERNAME_KEY = 'asistencia_username';

// El JWT ya trae `is_staff` en su payload (ver TokenConRolSerializer en el
// backend) — se decodifica acá en vez de pedirlo a otro endpoint aparte.
function esStaff(accessToken: string | null): boolean {
  if (!accessToken) return false;
  try {
    const payload = JSON.parse(atob(accessToken.split('.')[1]));
    return !!payload.is_staff;
  } catch {
    return false;
  }
}

// Sin esto, un token vencido en localStorage seguía contando como sesión: el
// agente veía el registro o el dashboard y recién al enviar algo le daba 401.
function vigente(accessToken: string | null): boolean {
  if (!accessToken) return false;
  try {
    const payload = JSON.parse(atob(accessToken.split('.')[1]));
    return typeof payload.exp === 'number' && payload.exp * 1000 > Date.now();
  } catch {
    return false;
  }
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  readonly username = signal<string | null>(localStorage.getItem(USERNAME_KEY));
  readonly isAuthenticated = signal<boolean>(false);
  readonly isStaff = signal<boolean>(false);

  constructor(private http: HttpClient) {
    const token = localStorage.getItem(ACCESS_KEY);
    this.isAuthenticated.set(vigente(token));
    this.isStaff.set(vigente(token) && esStaff(token));
    this.cerrarSiVencida();
  }

  /** Los guards la llaman antes de decidir: cubre el token que vence con la app abierta. */
  cerrarSiVencida(): void {
    const token = localStorage.getItem(ACCESS_KEY);
    if (token && !vigente(token)) this.logout();
  }

  async login(username: string, password: string): Promise<void> {
    const respuesta = await firstValueFrom(
      this.http.post<{ access: string; refresh: string }>(`${API_BASE_URL}/token/`, {
        username,
        password
      })
    );
    localStorage.setItem(ACCESS_KEY, respuesta.access);
    localStorage.setItem(REFRESH_KEY, respuesta.refresh);
    localStorage.setItem(USERNAME_KEY, username);
    this.username.set(username);
    this.isAuthenticated.set(true);
    this.isStaff.set(esStaff(respuesta.access));
  }

  logout(): void {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(USERNAME_KEY);
    this.username.set(null);
    this.isAuthenticated.set(false);
    this.isStaff.set(false);
  }

  getAccessToken(): string | null {
    return localStorage.getItem(ACCESS_KEY);
  }
}
