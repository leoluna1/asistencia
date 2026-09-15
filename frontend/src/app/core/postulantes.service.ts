import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { API_BASE_URL } from './api-base';
import { Postulante } from './models';

export interface ResultadoEncuadre {
  ok: boolean;
  motivo?: string;
}

export interface DatosRegistro {
  nombres: string;
  apellidos: string;
  cedula: string;
  estatura_cm: number;
  fecha_nacimiento: string;
  telefono: string;
  correo: string;
  genero: string;
  foto: Blob;
  password: string;
}

export interface DatosEdicionPostulante {
  nombres: string;
  apellidos: string;
  estatura_cm: number;
  fecha_nacimiento: string;
  telefono: string;
  correo: string;
  genero: string;
}

@Injectable({ providedIn: 'root' })
export class PostulantesService {
  constructor(private http: HttpClient) {}

  registrar(datos: DatosRegistro): Promise<Postulante> {
    const form = new FormData();
    form.append('nombres', datos.nombres);
    form.append('apellidos', datos.apellidos);
    form.append('cedula', datos.cedula);
    form.append('estatura_cm', String(datos.estatura_cm));
    form.append('fecha_nacimiento', datos.fecha_nacimiento);
    form.append('telefono', datos.telefono);
    form.append('correo', datos.correo);
    form.append('genero', datos.genero);
    form.append('foto', datos.foto, 'foto.jpg');
    form.append('password', datos.password);

    return firstValueFrom(this.http.post<Postulante>(`${API_BASE_URL}/postulantes/`, form));
  }

  miPostulante(): Promise<Postulante> {
    return firstValueFrom(this.http.get<Postulante>(`${API_BASE_URL}/mi-postulante/`));
  }

  actualizarMiPostulante(cambios: DatosEdicionPostulante): Promise<Postulante> {
    return firstValueFrom(
      this.http.patch<Postulante>(`${API_BASE_URL}/mi-postulante/`, cambios)
    );
  }

  probarEncuadre(frame: Blob): Promise<ResultadoEncuadre> {
    const form = new FormData();
    form.append('foto', frame, 'frame.jpg');
    return firstValueFrom(
      this.http.post<ResultadoEncuadre>(`${API_BASE_URL}/postulantes/probar-encuadre/`, form)
    );
  }
}
