import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { schedulesApi, type CreateScheduleData, type UpdateScheduleData } from '../lib/api';
import type { ScheduleListResponse } from '../types';

export function useSchedules() {
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery<ScheduleListResponse>({
    queryKey: ['schedules'],
    queryFn: () => schedulesApi.list(),
  });

  const createMutation = useMutation({
    mutationFn: (data: CreateScheduleData) => schedulesApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schedules'] });
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: UpdateScheduleData }) =>
      schedulesApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schedules'] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => schedulesApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schedules'] });
    },
  });

  const enableMutation = useMutation({
    mutationFn: (id: number) => schedulesApi.enable(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schedules'] });
    },
  });

  const disableMutation = useMutation({
    mutationFn: (id: number) => schedulesApi.disable(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schedules'] });
    },
  });

  const runNowMutation = useMutation({
    mutationFn: ({ id, dryRun }: { id: number; dryRun: boolean }) =>
      schedulesApi.runNow(id, dryRun),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schedules'] });
      queryClient.invalidateQueries({ queryKey: ['stats'] });
    },
  });

  return {
    schedules: data?.schedules || [],
    total: data?.total || 0,
    isLoading,
    error,
    create: createMutation.mutate,
    isCreating: createMutation.isPending,
    update: updateMutation.mutate,
    isUpdating: updateMutation.isPending,
    delete: deleteMutation.mutate,
    isDeleting: deleteMutation.isPending,
    enable: enableMutation.mutate,
    disable: disableMutation.mutate,
    runNow: runNowMutation.mutate,
    isRunning: runNowMutation.isPending,
  };
}
