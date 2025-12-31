import { useSchedules } from '../hooks/useSchedules';
import { formatRelativeTime, anonymizeGroupId } from '../lib/utils';
import type { Schedule } from '../types';

export default function Schedules() {
  const { schedules, isLoading, enable, disable, delete: deleteSchedule, runNow, isRunning } = useSchedules();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center py-12 text-gray-600 dark:text-gray-400">
          Loading schedules...
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white">
          Scheduled Summaries
        </h1>
      </div>

      {schedules.length === 0 ? (
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-12 text-center">
          <p className="text-gray-600 dark:text-gray-400 text-lg">
            No scheduled summaries yet.
          </p>
          <p className="text-gray-500 dark:text-gray-500 text-sm mt-2">
            Use the <code className="bg-gray-100 dark:bg-gray-700 px-1 rounded">!schedule</code> command in a Signal group to create schedules.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {schedules.map((schedule) => (
            <ScheduleCard
              key={schedule.id}
              schedule={schedule}
              onToggle={() => {
                schedule.enabled ? disable(schedule.id) : enable(schedule.id);
              }}
              onDelete={() => {
                if (confirm(`Delete schedule "${schedule.name}"?`)) {
                  deleteSchedule(schedule.id);
                }
              }}
              onRunNow={(dryRun) => runNow({ id: schedule.id, dryRun })}
              isRunning={isRunning}
            />
          ))}
        </div>
      )}

      <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
        <p className="text-sm text-blue-800 dark:text-blue-200">
          <strong>Privacy Note:</strong> Group names are hidden. Use the <code className="bg-blue-100 dark:bg-blue-800 px-1 rounded">!schedule</code> command in Signal to manage schedules.
        </p>
      </div>
    </div>
  );
}

function ScheduleCard({
  schedule,
  onToggle,
  onDelete,
  onRunNow,
  isRunning,
}: {
  schedule: Schedule;
  onToggle: () => void;
  onDelete: () => void;
  onRunNow: (dryRun: boolean) => void;
  isRunning: boolean;
}) {
  const dayNames = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 hover:shadow-lg transition-shadow">
      <div className="flex items-start justify-between mb-4">
        <div className="flex-1">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
            {schedule.name}
          </h3>
          <p className="text-sm text-gray-600 dark:text-gray-400 mt-1 font-mono">
            {anonymizeGroupId(schedule.source_group.group_id)} → {anonymizeGroupId(schedule.target_group.group_id)}
          </p>
        </div>
        <div className={`px-2 py-1 rounded text-xs font-medium ${
          schedule.enabled
            ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200'
            : 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300'
        }`}>
          {schedule.enabled ? 'Enabled' : 'Disabled'}
        </div>
      </div>

      <div className="space-y-2 text-sm text-gray-600 dark:text-gray-400">
        <div className="flex items-center gap-2">
          <span className="font-medium">Type:</span>
          <span className="capitalize">{schedule.schedule_type}</span>
        </div>
        {schedule.schedule_type === 'weekly' ? (
          <div className="flex items-center gap-2">
            <span className="font-medium">Day:</span>
            <span>{dayNames[schedule.schedule_day_of_week || 0]}</span>
          </div>
        ) : null}
        <div className="flex items-center gap-2">
          <span className="font-medium">Times:</span>
          <span>{schedule.schedule_times.join(', ')}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="font-medium">Timezone:</span>
          <span>{schedule.timezone}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="font-medium">Period:</span>
          <span>{schedule.summary_period_hours} hours</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="font-medium">Retention:</span>
          <span>{schedule.retention_hours} hours</span>
        </div>
        {schedule.last_run && (
          <div className="flex items-center gap-2">
            <span className="font-medium">Last run:</span>
            <span>{formatRelativeTime(schedule.last_run)}</span>
          </div>
        )}
      </div>

      <div className="mt-4 flex gap-2">
        <button
          onClick={onToggle}
          className="flex-1 px-3 py-2 text-sm bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
        >
          {schedule.enabled ? 'Disable' : 'Enable'}
        </button>
        <button
          onClick={() => onRunNow(true)}
          disabled={isRunning}
          className="flex-1 px-3 py-2 text-sm bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-200 rounded hover:bg-blue-200 dark:hover:bg-blue-800 transition-colors disabled:opacity-50"
        >
          Dry Run
        </button>
        <button
          onClick={() => onRunNow(false)}
          disabled={isRunning}
          className="flex-1 px-3 py-2 text-sm bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-200 rounded hover:bg-green-200 dark:hover:bg-green-800 transition-colors disabled:opacity-50"
        >
          Run Now
        </button>
        <button
          onClick={onDelete}
          className="px-3 py-2 text-sm bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-200 rounded hover:bg-red-200 dark:hover:bg-red-800 transition-colors"
        >
          Delete
        </button>
      </div>
    </div>
  );
}
