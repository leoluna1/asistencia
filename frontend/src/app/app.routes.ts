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
    loadComponent: () => import('./features/verificar/verificar').then((m) => m.Verificar)
  },
  {
    path: 'registro',
    loadComponent: () => import('./features/registro/registro').then((m) => m.Registro)
  },
  {
    path: 'login',
    loadComponent: () => import('./features/login/login').then((m) => m.Login)
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
