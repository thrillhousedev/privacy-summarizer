import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { groupsApi } from '../lib/api';
import type { GroupListResponse } from '../types';

export function useGroups() {
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery<GroupListResponse>({
    queryKey: ['groups'],
    queryFn: groupsApi.list,
  });

  const syncMutation = useMutation({
    mutationFn: groupsApi.sync,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['groups'] });
    },
  });

  return {
    groups: data?.groups || [],
    total: data?.total || 0,
    isLoading,
    error,
    sync: syncMutation.mutate,
    isSyncing: syncMutation.isPending,
    syncError: syncMutation.error,
  };
}
