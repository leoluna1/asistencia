// En producción la SPA y la API salen del mismo nginx: '/api' relativo. Solo
// `ng serve` (puerto 4200) habla con el runserver de Django en :8000.
export const API_BASE_URL =
  location.port === '4200' ? 'http://localhost:8000/api' : '/api';
