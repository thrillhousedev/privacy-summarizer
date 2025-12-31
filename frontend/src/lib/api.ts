import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios';

const API_URL = import.meta.env.VITE_API_URL || '';

// Create axios instance
const axiosInstance = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add API key to requests
axiosInstance.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const apiKey = localStorage.getItem('apiKey');
    if (apiKey && config.headers) {
      config.headers['X-API-Key'] = apiKey;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Handle 401 errors (unauthorized)
axiosInstance.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('apiKey');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export const api = axiosInstance;

// Health API - used for validating API key
export const healthApi = {
  check: async () => {
    const response = await api.get('/api/health');
    return response.data;
  },
};

// Groups API
export const groupsApi = {
  list: async () => {
    const response = await api.get('/api/groups');
    return response.data;
  },

  get: async (groupId: string) => {
    const response = await api.get(`/api/groups/${groupId}`);
    return response.data;
  },

  sync: async () => {
    const response = await api.post('/api/groups/sync');
    return response.data;
  },
};

// Stats API
export const statsApi = {
  getPending: async () => {
    const response = await api.get('/api/stats/pending');
    return response.data;
  },

  getRecentRuns: async (limit = 20) => {
    const response = await api.get('/api/stats/runs', { params: { limit } });
    return response.data;
  },

  getGroupStats: async (groupId: string) => {
    const response = await api.get(`/api/stats/groups/${groupId}`);
    return response.data;
  },
};

// Schedules API
export const schedulesApi = {
  list: async (enabledOnly = false) => {
    const response = await api.get('/api/schedules', {
      params: { enabled_only: enabledOnly },
    });
    return response.data;
  },

  get: async (id: number) => {
    const response = await api.get(`/api/schedules/${id}`);
    return response.data;
  },

  create: async (data: CreateScheduleData) => {
    const response = await api.post('/api/schedules', data);
    return response.data;
  },

  update: async (id: number, data: UpdateScheduleData) => {
    const response = await api.put(`/api/schedules/${id}`, data);
    return response.data;
  },

  delete: async (id: number) => {
    await api.delete(`/api/schedules/${id}`);
  },

  enable: async (id: number) => {
    const response = await api.post(`/api/schedules/${id}/enable`);
    return response.data;
  },

  disable: async (id: number) => {
    const response = await api.post(`/api/schedules/${id}/disable`);
    return response.data;
  },

  runNow: async (id: number, dryRun = false) => {
    const response = await api.post(`/api/schedules/${id}/run`, null, {
      params: { dry_run: dryRun },
    });
    return response.data;
  },

  getRuns: async (id: number, limit = 10) => {
    const response = await api.get(`/api/schedules/${id}/runs`, { params: { limit } });
    return response.data;
  },

  resend: async (scheduleId: number, runId: number, dryRun = false) => {
    const response = await api.post(
      `/api/schedules/${scheduleId}/runs/${runId}/resend`,
      null,
      { params: { dry_run: dryRun } }
    );
    return response.data;
  },
};

// Type definitions
export interface CreateScheduleData {
  name: string;
  source_group_id: number;
  target_group_id: number;
  schedule_times: string[];
  timezone: string;
  summary_period_hours: number;
  schedule_type: 'daily' | 'weekly';
  schedule_day_of_week?: number;
  retention_hours: number;
  enabled: boolean;
}

export interface UpdateScheduleData {
  schedule_times?: string[];
  timezone?: string;
  summary_period_hours?: number;
  retention_hours?: number;
  enabled?: boolean;
}
