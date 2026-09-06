import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { API_BASE_URL } from './api-base';
import { Postulante } from './models';

export interface DatosRegistro {
  nombres: string;
  apellidos: string;
  cedula: string;
  estatura_cm: number;
  sede: string;
  foto: Blob;
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
    form.append('sede', datos.sede);
    form.append('foto', datos.foto, 'foto.jpg');

    return firstValueFrom(this.http.post<Postulante>(`${API_BASE_URL}/postulantes/`, form));
  }
}
