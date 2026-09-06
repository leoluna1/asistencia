export interface Postulante {
  id: number;
  nombres: string;
  apellidos: string;
  cedula: string;
  estatura_cm: number;
  foto: string;
  sede: string;
  creado_en: string;
}

export interface ResultadoVerificacion {
  verificado: boolean;
  motivo?: 'no_se_detecto_rostro' | 'sin_coincidencia';
  confianza?: number | null;
  ya_registrado?: boolean;
  postulante?: Postulante;
  verificado_en?: string;
}

export interface ResultadoManual {
  verificado: boolean;
  ya_registrado: boolean;
  metodo: 'MANUAL';
  forzado_por: string | null;
  postulante: Postulante;
  verificado_en: string;
}

export interface FilaAsistencia {
  id: number;
  postulante_cedula: string;
  postulante_nombres: string;
  postulante_apellidos: string;
  postulante_foto: string;
  sede: string;
  metodo: 'AUTO' | 'MANUAL';
  confianza: number | null;
  verificado_en: string;
}
