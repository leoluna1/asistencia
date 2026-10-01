import { Routes } from '@angular/router';
import { adminGuard, authGuard } from './core/auth.guard';

export const routes: Routes = [
  {
    path: '',
    pathMatch: 'full',
    loadComponent: () => import('./features/inicio/inicio').then((m) => m.Inicio)
  },
  {
    path: 'verificar',
    // El kiosco lo abre un agente logueado (la API exige is_staff, ver
    // VerificarAsistenciaView); el postulante solo se sienta frente a la cámara.
    canActivate: [adminGuard],
    loadComponent: () => import('./features/verificar/verificar').then((m) => m.Verificar)
  },
  {
    path: 'registro',
    // Puesto de registro supervisado: lo abre un agente (la API exige is_staff,
    // ver RegistroPostulanteView), que confirma la cédula física.
    canActivate: [adminGuard],
    loadComponent: () => import('./features/registro/registro').then((m) => m.Registro)
  },
  {
    path: 'login',
    loadComponent: () => import('./features/login/login').then((m) => m.Login)
  },
  {
    path: 'recuperar',
    loadComponent: () => import('./features/recuperar/recuperar').then((m) => m.Recuperar)
  },
  {
    path: 'dashboard',
    canActivate: [adminGuard],
    loadComponent: () => import('./features/dashboard/dashboard').then((m) => m.Dashboard)
  },
  {
    path: 'mi-postulante',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./features/mi-postulante/mi-postulante').then((m) => m.MiPostulante)
  },
  { path: '**', redirectTo: '' }
];
