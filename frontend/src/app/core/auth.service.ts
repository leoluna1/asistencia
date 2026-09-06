import { Injectable, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { API_BASE_URL } from './api-base';

const ACCESS_KEY = 'asistencia_access_token';
const REFRESH_KEY = 'asistencia_refresh_token';
const USERNAME_KEY = 'asistencia_username';

@Injectable({ providedIn: 'root' })
export class AuthService {
  readonly username = signal<string | null>(localStorage.getItem(USERNAME_KEY));
  readonly isAuthenticated = signal<boolean>(!!localStorage.getItem(ACCESS_KEY));

  constructor(private http: HttpClient) {}

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
  }

  logout(): void {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(USERNAME_KEY);
    this.username.set(null);
    this.isAuthenticated.set(false);
  }

  getAccessToken(): string | null {
    return localStorage.getItem(ACCESS_KEY);
  }
}
