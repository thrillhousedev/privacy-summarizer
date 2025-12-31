import { useQuery } from '@tanstack/react-query';
import { statsApi } from '../lib/api';
import type { PendingStats, RecentRunsResponse } from '../types';

const defaultPending: PendingStats = {
  total_messages: 0,
  messages_by_group: {},
  oldest_message: undefined,
  newest_message: undefined,
};

export function useStats() {
  const pendingQuery = useQuery<PendingStats>({
    queryKey: ['stats', 'pending'],
    queryFn: statsApi.getPending,
    refetchInterval: 30000,
  });

  const runsQuery = useQuery<RecentRunsResponse>({
    queryKey: ['stats', 'runs'],
    queryFn: () => statsApi.getRecentRuns(10),
    refetchInterval: 30000,
  });

  // Safely extract data with defaults
  const pending = pendingQuery.data ?? defaultPending;
  const runs = Array.isArray(runsQuery.data?.runs) ? runsQuery.data.runs : [];

  return {
    pending,
    runs,
    isLoading: pendingQuery.isLoading || runsQuery.isLoading,
    error: pendingQuery.error || runsQuery.error,
  };
}
