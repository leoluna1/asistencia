import { TestBed } from '@angular/core/testing';
import { asegurarLocalStorage } from './testing-storage';

asegurarLocalStorage();
import { provideHttpClient } from '@angular/common/http';
import { provideRouter, Router, UrlTree } from '@angular/router';
import { adminGuard } from './auth.guard';

describe('adminGuard', () => {
  it('manda al login explicando que la sección es solo para agentes', () => {
    localStorage.clear();
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideRouter([])] });
    const resultado = TestBed.runInInjectionContext(() => adminGuard({} as any, {} as any)) as UrlTree;
    expect(TestBed.inject(Router).serializeUrl(resultado)).toBe('/login?motivo=solo-agentes');
  });
});
