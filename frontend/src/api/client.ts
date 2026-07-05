import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios';
import { useAuthStore } from '../store/authStore';

const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

export const apiClient = axios.create({
  baseURL: BASE_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: 10_000,
});

// ── Request interceptor — attach Bearer token ─────────────────────────────────
apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = useAuthStore.getState().accessToken;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// ── Response interceptor — 401 → refresh → retry ─────────────────────────────
let _isRefreshing = false;
type QueueEntry = { resolve: (token: string) => void; reject: (err: unknown) => void };
let _queue: QueueEntry[] = [];

function flushQueue(err: unknown, token: string | null): void {
  _queue.forEach(({ resolve, reject }) => (err ? reject(err) : resolve(token!)));
  _queue = [];
}

apiClient.interceptors.response.use(
  (res) => res,
  async (error: AxiosError) => {
    const original = error.config as InternalAxiosRequestConfig & { _retry?: boolean };

    if (error.response?.status !== 401 || original._retry) {
      return Promise.reject(error);
    }

    const store = useAuthStore.getState();
    const refreshToken = store.refreshToken;

    if (!refreshToken) {
      store.logout();
      return Promise.reject(error);
    }

    if (_isRefreshing) {
      return new Promise<string>((resolve, reject) => {
        _queue.push({ resolve, reject });
      }).then((newToken) => {
        original._retry = true;
        original.headers.Authorization = `Bearer ${newToken}`;
        return apiClient(original);
      });
    }

    original._retry = true;
    _isRefreshing = true;

    try {
      const { data } = await axios.post<{ access_token: string }>(`${BASE_URL}/auth/refresh`, {
        refresh_token: refreshToken,
      });
      const newToken = data.access_token;
      useAuthStore.getState().setAccessToken(newToken);
      flushQueue(null, newToken);
      original.headers.Authorization = `Bearer ${newToken}`;
      return apiClient(original);
    } catch (refreshErr) {
      flushQueue(refreshErr, null);
      useAuthStore.getState().logout();
      return Promise.reject(refreshErr);
    } finally {
      _isRefreshing = false;
    }
  }
);
