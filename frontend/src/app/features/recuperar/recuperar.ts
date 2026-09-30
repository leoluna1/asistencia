import { Component, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { InlineMessage } from '../../shared/inline-message/inline-message';
import { PostulantesService } from '../../core/postulantes.service';
import { primerMensajeDeError } from '../../core/errores';
import { soloDigitos } from '../../core/validators';

@Component({
  selector: 'app-recuperar',
  standalone: true,
  imports: [
    FormsModule,
    RouterLink,
    MatButtonModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatProgressSpinnerModule,
    InlineMessage
  ],
  templateUrl: './recuperar.html',
  styleUrl: './recuperar.scss'
})
export class Recuperar {
  cedula = '';
  codigo = '';
  passwordNueva = '';

  readonly paso = signal<'cedula' | 'codigo'>('cedula');
  readonly enviando = signal(false);
  readonly error = signal<string | null>(null);
  readonly restableciendo = signal(false);
  readonly errorCodigo = signal<string | null>(null);
  readonly exito = signal(false);

  constructor(
    private postulantes: PostulantesService,
    private router: Router
  ) {}

  onCedulaInput(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.cedula = soloDigitos(input.value, 10);
    input.value = this.cedula;
  }

  async solicitarCodigo(): Promise<void> {
    if (this.cedula.length !== 10) return;
    this.enviando.set(true);
    this.error.set(null);
    try {
      await this.postulantes.solicitarRecuperacion(this.cedula);
      this.paso.set('codigo');
    } catch (e: any) {
      this.error.set(primerMensajeDeError(e?.error) || 'No se pudo enviar el código.');
    } finally {
      this.enviando.set(false);
    }
  }

  async restablecer(): Promise<void> {
    if (!this.codigo || this.passwordNueva.length < 8) return;
    this.restableciendo.set(true);
    this.errorCodigo.set(null);
    try {
      await this.postulantes.restablecerPassword(this.cedula, this.codigo, this.passwordNueva);
      this.exito.set(true);
    } catch (e: any) {
      this.errorCodigo.set(
        primerMensajeDeError(e?.error) || 'No se pudo restablecer la contraseña.'
      );
    } finally {
      this.restableciendo.set(false);
    }
  }

  irALogin(): void {
    this.router.navigate(['/login']);
  }
}
