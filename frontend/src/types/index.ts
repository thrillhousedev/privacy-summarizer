// Group types
export interface Group {
  id: number;
  group_id: string;
  name: string;
  description?: string;
  pending_messages: number;
  created_at: string;
  updated_at: string;
}

export interface GroupListResponse {
  groups: Group[];
  total: number;
}

// Schedule types
export interface GroupInfo {
  id: number;
  group_id: string;
  name: string;
}

export interface Schedule {
  id: number;
  name: string;
  source_group: GroupInfo;
  target_group: GroupInfo;
  schedule_times: string[];
  timezone: string;
  summary_period_hours: number;
  schedule_type: 'daily' | 'weekly';
  schedule_day_of_week?: number;
  retention_hours: number;
  enabled: boolean;
  last_run?: string;
  created_at: string;
  updated_at: string;
}

export interface ScheduleListResponse {
  schedules: Schedule[];
  total: number;
}

// Stats types
export interface PendingStats {
  total_messages: number;
  messages_by_group: Record<string, number>;
  oldest_message?: string;
  newest_message?: string;
}

export interface SummaryRun {
  id: number;
  schedule_id: number;
  schedule_name?: string;
  started_at: string;
  completed_at?: string;
  message_count: number;
  status: 'pending' | 'completed' | 'failed';
  summary_text?: string;
  error_message?: string;
}

export interface RecentRunsResponse {
  runs: SummaryRun[];
  total: number;
}

// Health types
export interface HealthStatus {
  status: string;
  database: string;
  ollama: string;
  signal_cli: string;
  timestamp: string;
  message?: string;
}
