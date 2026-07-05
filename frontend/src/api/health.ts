import { apiClient } from './client';

export interface HealthResponse {
  status: 'ok' | 'degraded' | 'error';
  database: 'connected' | 'disconnected';
  version: string;
}

export async function fetchHealth(): Promise<HealthResponse> {
  const { data } = await apiClient.get<HealthResponse>('/health');
  return data;
}
