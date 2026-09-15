import { Component, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { AuthService } from '../../core/auth.service';
import { PostulantesService } from '../../core/postulantes.service';
import { Postulante } from '../../core/models';
import { primerMensajeDeError } from '../../core/errores';

@Component({
  selector: 'app-mi-postulante',
  standalone: true,
  imports: [
    FormsModule,
    MatButtonModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule
  ],
  templateUrl: './mi-postulante.html',
  styleUrl: './mi-postulante.scss'
})
export class MiPostulante implements OnInit {
  readonly cargando = signal(true);
  readonly guardando = signal(false);
  readonly error = signal<string | null>(null);
  readonly exito = signal(false);
  readonly postulante = signal<Postulante | null>(null);

  nombres = '';
  apellidos = '';
  estatura_cm: number | null = null;
  fecha_nacimiento = '';
  telefono = '';
  correo = '';
  genero = '';

  constructor(
    private postulantes: PostulantesService,
    private auth: AuthService,
    private router: Router
  ) {}

  async ngOnInit(): Promise<void> {
    try {
      const datos = await this.postulantes.miPostulante();
      this.postulante.set(datos);
      this.nombres = datos.nombres;
      this.apellidos = datos.apellidos;
      this.estatura_cm = datos.estatura_cm;
      this.fecha_nacimiento = datos.fecha_nacimiento;
      this.telefono = datos.telefono;
      this.correo = datos.correo;
      this.genero = datos.genero;
    } catch {
      // Esta cuenta no tiene un Postulante propio (es un agente) — /mi-postulante
      // no le corresponde.
      this.router.navigate(['/dashboard']);
      return;
    } finally {
      this.cargando.set(false);
    }
  }

  get datosCompletos(): boolean {
    return !!(
      this.nombres &&
      this.apellidos &&
      this.estatura_cm &&
      this.fecha_nacimiento &&
      this.telefono &&
      this.correo &&
      this.genero
    );
  }

  async guardar(): Promise<void> {
    if (!this.datosCompletos) return;
    this.guardando.set(true);
    this.error.set(null);
    this.exito.set(false);
    try {
      const actualizado = await this.postulantes.actualizarMiPostulante({
        nombres: this.nombres,
        apellidos: this.apellidos,
        estatura_cm: this.estatura_cm!,
        fecha_nacimiento: this.fecha_nacimiento,
        telefono: this.telefono,
        correo: this.correo,
        genero: this.genero
      });
      this.postulante.set(actualizado);
      this.exito.set(true);
    } catch (e: any) {
      this.error.set(primerMensajeDeError(e?.error) || 'No se pudieron guardar los cambios.');
    } finally {
      this.guardando.set(false);
    }
  }

  cerrarSesion(): void {
    this.auth.logout();
    this.router.navigate(['/']);
  }
}
