import { apiClient } from './client';

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface AccessTokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface UserResponse {
  id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  is_superuser: boolean;
  created_at: string;
  updated_at: string;
}

export const authApi = {
  register: async (email: string, password: string, full_name?: string): Promise<TokenResponse> => {
    const { data } = await apiClient.post<TokenResponse>('/auth/register', {
      email,
      password,
      full_name,
    });
    return data;
  },

  login: async (email: string, password: string): Promise<TokenResponse> => {
    const { data } = await apiClient.post<TokenResponse>('/auth/login', {
      email,
      password,
    });
    return data;
  },

  logout: async (refreshToken: string): Promise<void> => {
    await apiClient.post('/auth/logout', { refresh_token: refreshToken });
  },

  me: async (): Promise<UserResponse> => {
    const { data } = await apiClient.get<UserResponse>('/users/me');
    return data;
  },

  updateMe: async (full_name: string): Promise<UserResponse> => {
    const { data } = await apiClient.patch<UserResponse>('/users/me', { full_name });
    return data;
  },
};
