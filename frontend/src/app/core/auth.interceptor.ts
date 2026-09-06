import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { AuthService } from './auth.service';

// ponytail: sin refresh automático en 401 todavía — el access token dura poco (default
// simplejwt) y para un kiosco/dashboard basta con volver a loguearse si expira mientras
// se usa. Agregar retry-con-refresh si en la práctica resulta molesto.
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const token = inject(AuthService).getAccessToken();
  if (!token) {
    return next(req);
  }
  return next(req.clone({ setHeaders: { Authorization: `Bearer ${token}` } }));
};
