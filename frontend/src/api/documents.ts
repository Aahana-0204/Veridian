import { apiClient } from './client';

export type DocumentStatus = 'queued' | 'processing' | 'ready' | 'failed';
export type FileType = 'pdf' | 'docx' | 'txt' | 'md' | 'html';

export interface DocumentResponse {
  id: string;
  user_id: string;
  title: string;
  filename: string;
  file_type: FileType;
  file_size: number;
  status: DocumentStatus;
  chunk_count: number;
  error_message: string | null;
  content_hash: string | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentListResponse {
  items: DocumentResponse[];
  total: number;
  page: number;
  size: number;
  pages: number;
}

export interface DocumentStatusResponse {
  id: string;
  status: DocumentStatus;
  chunk_count: number;
  error_message: string | null;
}

export const documentsApi = {
  upload: async (
    file: File,
    title?: string,
    onProgress?: (pct: number) => void
  ): Promise<DocumentResponse> => {
    const form = new FormData();
    form.append('file', file);
    if (title) form.append('title', title);

    const { data } = await apiClient.post<DocumentResponse>('/documents/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (e) => {
        if (onProgress && e.total) {
          onProgress(Math.round((e.loaded * 100) / e.total));
        }
      },
    });
    return data;
  },

  list: async (page = 1, size = 20): Promise<DocumentListResponse> => {
    const { data } = await apiClient.get<DocumentListResponse>('/documents', {
      params: { page, size },
    });
    return data;
  },

  getStatus: async (id: string): Promise<DocumentStatusResponse> => {
    const { data } = await apiClient.get<DocumentStatusResponse>(`/documents/${id}/status`);
    return data;
  },

  delete: async (id: string): Promise<void> => {
    await apiClient.delete(`/documents/${id}`);
  },
};
