import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { CanActivateFn } from '@angular/router';
import { AuthService } from './auth.service';

export const authGuard: CanActivateFn = () => {
  if (inject(AuthService).isAuthenticated()) {
    return true;
  }
  return inject(Router).createUrlTree(['/login']);
};

// El dashboard es solo para agentes (is_staff) — la API ya lo exige
// (ListaAsistenciasView/ForzarAsistenciaView usan IsAdminUser), esto evita
// que un postulante logueado llegue a ver la pantalla vacía/rota porque sus
// pedidos a la API le vuelven 403. A un postulante autenticado lo manda a su
// propio panel en vez de al login (ya inició sesión, solo no tiene permiso acá).
export const adminGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  if (auth.isStaff()) {
    return true;
  }
  const router = inject(Router);
  return router.createUrlTree([auth.isAuthenticated() ? '/mi-postulante' : '/login']);
};
